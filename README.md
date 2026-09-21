# Мониторинг лесных пожаров

Веб-приложение для поиска тепловых очагов и картирования гари по спутниковым данным. Пользователь задаёт область на карте и интервал дат; бэкенд собирает FIRMS, Landsat и Sentinel-2, а на карте появляются очаги, отсеянные точки и полигоны гари со степенью поражения.

## Как это работает

1. На карте рисуется прямоугольник (WGS84, не больше 10 000 км²) и выбираются даты (не больше 90 дней).
2. Бэкенд ставит задачу в очередь и обрабатывает её в фоне.
3. Интерфейс опрашивает статус и подгружает готовые слои GeoJSON.

### Пайплайн

```
FIRMS (MODIS / VIIRS)
        ↓
фильтр и кластеризация
        ↓
подтверждение крупных очагов Landsat TIRS (по возможности)
        ↓
Sentinel-2: NBR до и после пожара → dNBR
        ↓
маскирование лесом (ESA WorldCover) и полигоны гари
```

**Очаги.** NASA FIRMS отдаёт CSV по тепловым каналам MODIS и VIIRS. Для недавних дат берётся near-real-time продукт, для более старых — standard processing. Точки отсеиваются, если это вулкан, стационарный источник, море, дневной низкий confidence, не растительность (WorldCover) или слишком частые срабатывания в одной ячейке. Оставшиеся группируются DBSCAN с радиусом ~2 км.

**Landsat.** Для крупных очагов ищутся сцены Landsat Collection 2 Level-2. Аномалия поверхностной температуры по TIRS помечает точку как подтверждённую. Если сцен нет, шаг пропускается, очаги FIRMS всё равно остаются.

**Гарь.** По датам очагов выбираются окна Sentinel-2 L2A: примерно 60–5 дней до первого очага и до 30 дней после последнего. Считается NBR, затем dNBR = NBR_до − NBR_после. Классы dNBR — пороги USGS / Key & Benson:

| Класс | dNBR |
|---|---|
| слабое | 0.10–0.27 |
| умеренное | 0.27–0.44 |
| сильное | 0.44–0.66 |
| очень сильное | ≥ 0.66 |

Гарь ограничивается лесом и манграми WorldCover, мелкий шум убирается морфологией. Полигоны дальше  от очагов помечаются как неуверенные.

Снимки Landsat, Sentinel-2 и WorldCover читаются как Cloud-Optimized GeoTIFF через Microsoft Planetary Computer STAC. Кэш задач лежит в `backend/data/jobs/`.

### Интерфейс

Карта на MapLibre: спутниковая подложка, рисование bbox двумя кликами, слои очагов и гари. В боковой панели — даты, кнопка «Пример: Якутия» (июль 2021), сводка по площади гари и числу очагов.

Оценка dNBR без полевой калибровки — ориентир, не юридический акт. FIRMS не видит слабые пожары под облаком.

## Стек

| Часть | Технологии |
|---|---|
| Бэкенд | Python 3.10+, FastAPI, pandas, GeoPandas, rasterio, scikit-learn |
| Фронтенд | React 19, TypeScript, Vite, MapLibre GL |
| Данные | NASA FIRMS, Planetary Computer (Sentinel-2, Landsat, WorldCover) |

## Требования

- Python 3.10 или новее (предпочтительно 3.12)
- Node.js 18+ и npm
- Доступ в интернет: FIRMS и Planetary Computer
- Бесплатный [FIRMS MAP key](https://firms.modaps.eosdis.nasa.gov/api/area/)

Опционально: [ключ Planetary Computer](https://planetarycomputer.microsoft.com/account) — ускоряет и стабилизирует скачивание COG, без него публичный доступ тоже работает.

## Установка

Из корня репозитория:

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

Скрипт создаёт `backend/.env` из примера, виртуальное окружение Python, ставит зависимости бэкенда и `npm install` для фронтенда.

Вручную:

```bash
cp backend/.env.example backend/.env
# вставьте FIRMS_MAP_KEY в backend/.env

cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd ../frontend
npm install
```

### Переменные окружения

Файл `backend/.env`:

```
FIRMS_MAP_KEY=ваш_ключ
PC_SDK_SUBSCRIPTION_KEY=          # необязательно
MAX_AOI_KM2=10000
DATA_DIR=data
```

## Запуск

Нужны два процесса.

Бэкенд (порт 8000):

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Фронтенд (порт 5173, API проксируется на бэкенд):

```bash
cd frontend
npm run dev
```

Откройте [http://127.0.0.1:5173](http://127.0.0.1:5173).

Проверка API: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) — в ответе `"firms_key": true`, если ключ задан.

### Как пользоваться

1. Выберите даты или нажмите «Пример: Якутия».
2. «Нарисовать область» — два клика по углам прямоугольника (или используйте пресет).
3. «Найти очаги и гари» и дождитесь статуса «Готово».
4. На карте: оранжевые точки — очаги, голубые — подтверждённые Landsat, цветные полигоны — степень гари. Чекбокс «Отсеянные очаги» показывает отфильтрованные точки.

Первый расчёт может занять несколько минут: качаются растры Sentinel-2 и Landsat.

## API

Базовый URL: `http://127.0.0.1:8000`.

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | Живость сервиса и наличие ключа FIRMS |
| `POST` | `/api/jobs` | Создать задачу: `{ "bbox": [west, south, east, north], "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD" }` |
| `GET` | `/api/jobs/{id}` | Статус и сводка |
| `GET` | `/api/jobs/{id}/hotspots` | Принятые очаги (GeoJSON) |
| `GET` | `/api/jobs/{id}/rejected` | Отсеянные очаги (GeoJSON) |
| `GET` | `/api/jobs/{id}/burns` | Полигоны гари (GeoJSON) |
| `GET` | `/api/jobs/{id}/summary` | Числовая сводка |

Статусы задачи: `queued` → `hotspots` → `burns` → `done` (или `error`).

## Структура репозитория

```
backend/                 FastAPI, пайплайн, сервисы спутниковых данных
  app/main.py           HTTP API
  app/pipeline.py       оркестрация расчёта
  app/services/         FIRMS, Landsat, Sentinel-2, WorldCover, гарь
frontend/               React + MapLibre
scripts/setup.sh        установка зависимостей
```
