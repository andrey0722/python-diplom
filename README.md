# Backend-сервис автоматизации закупок

Backend-приложение на Django REST Framework для автоматизации закупок в розничной сети. Проект позволяет поставщикам загружать прайс-листы, покупателям собирать корзину и оформлять заказы, а администраторам управлять заказами и справочниками через Django Admin.

## Возможности

- регистрация пользователей, подтверждение email, аутентификация по токену и сброс пароля;
- загрузка прайс-листов в формате YAML поставщика по URL (в режиме `DEBUG` доступна схема `file://` для локальных файлов);
- валидация прайс-листа: уникальность категорий и товаров, корректность ссылок товара на категорию;
- каталог магазинов, категорий и товарных предложений с фильтрацией, поиском и пагинацией;
- корзина покупателя с добавлением, изменением количества и удалением позиций;
- оформление заказа с резервированием остатков на складе магазинов;
- отмена заказа с возвратом зарезервированного количества к другим заказам;
- жизненный цикл заказа: `new`, `confirmed`, `assembled`, `sent`, `completed`, `cancelled`;
- отдельные API-методы для поставщика: обновление прайса, включение или отключение приема заказов, просмотр заказов по своему магазину;
- расширенная Django Admin: редактирование данных, оформление корзины, ограниченные переходы статусов заказа, защита активных заказов от некорректного редактирования;
- email-уведомления через Celery: подтверждение email, сброс пароля, создание заказа, отмена заказа, смена статуса, уведомления администраторам магазинов;
- окружение Docker Compose с backend, PostgreSQL, Redis, Celery, Nginx и Mailpit для разработки.

## Стек технологий

- Python 3.14+;
- Django 6.0, Django REST Framework;
- PostgreSQL для Docker-запуска, SQLite возможен для локальной разработки;
- Redis в качестве брокера Celery;
- Celery для фоновой отправки email;
- django-filter, django-environ, django-admin-extra-buttons;
- Mailpit в dev-окружении для просмотра отправляемых писем и отладки;
- Uvicorn ASGI server и Nginx reverse proxy.

## Структура проекта

```text
api/                    Основное приложение: модели, API views, serializers, services, admin, Celery tasks
api/templates/api/       TXT/HTML email-шаблоны
api/management/commands/ Команда manage.py celery для dev-worker с autoreload
project/                Настройки Django, URLconf, ASGI/WSGI, Celery app, health-check
shop_data/              Примеры YAML-прайсов и некорректные файлы для проверки валидации
compose.py              Обертка над Docker Compose командами для dev/prod окружений
docker-compose.yml      Базовое Compose-окружение
docker-compose.dev.yml  Dev-расширение: порты, Mailpit, init-сервисы, watch
Dockerfile              Backend-образ
example_sync.py         Синхронный пример работы с API
example_async.py        Асинхронный пример работы с API
```

## Переменные окружения

Создайте `.env` из примера перед запуском:

```powershell
Copy-Item .env.example .env
```

На Linux/macOS аналогичная команда:

```bash
cp .env.example .env
```

Переменные из `.env.example`:

| Переменная | Назначение | Пример |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Секретный ключ Django. Для production задайте уникальное случайное значение. | `django-example-key` |
| `DJANGO_DEBUG` | Включает режим разработки. В `True` доступен Debug Toolbar, подробные ответы и `file://` URL для импорта прайсов. | `True` |
| `DJANGO_ALLOWED_HOSTS` | Список разрешенных host-имен через запятую. Для локальной разработки допустим `*`. | `localhost,127.0.0.1` |
| `DATABASE_URL` | URL подключения к базе данных в формате `django-environ`. Для Docker backend получает внутренний PostgreSQL URL из Compose. | `postgres://user:password@localhost:5432/database` |
| `CELERY_BROKER_URL` | URL брокера Celery. В проекте используется Redis. | `redis://default:redis_password@localhost:6379/0` |
| `CELERY_WORKER_CONCURRENCY` | Количество процессов или потоков worker-а Celery. Для dev=режима достаточно `1`. | `1` |
| `EMAIL_URL` | Настройка email backend для отправки email. Закомментированные строки в `.env.example` являются альтернативными настройками. | `filemail:///email` |
| `LISTEN_PORT` | Внешний порт Nginx proxy при Docker-запуске. | `8080` |
| `SQL_TRACE` | Включает подробное логирование каждого выполняемого SQL-запроса в Django Database Backend и middleware со статистикой запросов. Полезно для отладки ORM и SQL-запросов. | `False` |

Варианты `EMAIL_URL`:

- `filemail:///email` сохраняет сырые email-письма в локальную директорию `email` (относительно Celery backend);
- `consolemail://` выводит письма в стандартный поток вывода Celery backend;
- `smtp://localhost:1025` использовать локальный SMTP для отладки;
- `smtp+tls://user:password@smtp.example.com:587` - пример реального SMTP-сервиса в production-like варианте.

Для Docker dev-окружения с Mailpit доступен вариант с `EMAIL_URL=smtp://smtp:1025`, это значение по умолчанию
для dev-конфигурации. Чтобы его использовать, достаточно закомментировать все значения `EMAIL_URL` в `.env`.

Дополнительно Docker Compose понимает переменные `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `REDIS_PASSWORD`, `IMAGE_TAG`, `COMPOSE_PROJECT_NAME` и `STATIC_ROOT`, если их нужно переопределить.

## Запуск через Docker для разработки

Этот вариант поднимает backend, PostgreSQL, Redis, Celery, Nginx и Mailpit.

1. Создайте `.env` и оставьте `DJANGO_DEBUG=True`.
   Для просмотра писем в Mailpit замените `EMAIL_URL` на `smtp://smtp:1025` или не указывайте совсем.
2. Инициализируйте окружение:

   ```powershell
   python compose.py dev init
   ```

   Команда выполнит миграции, соберет static-файлы, создаст dev-администратора и запустит `manage.py check`.

3. Запустите сервисы:

   ```powershell
   python compose.py dev up-build
   ```

После запуска доступны:

- API напрямую: `http://127.0.0.1:8000/api/v1/`;
- API через Nginx: `http://127.0.0.1:8080/api/v1/`;
- Django Admin: `http://127.0.0.1:8000/admin/`;
- Django Admin через Nginx: `http://127.0.0.1:8080/admin/`;
- Mailpit Web UI: `http://127.0.0.1:8025/`;
- PostgreSQL: `postgres://postgres_user:postgres_password@127.0.0.1:55432/db`, если используется значения по умолчанию.

Dev-администратор создается с email `admin@example.com` и паролем `123`. Эти данные предназначены только для локальной разработки.

Для более удобного переключения между разными конфигурациями Compose имеется специальный runner-скрипт compose.py.
Полезные команды для dev-конфигурации:

```powershell
python compose.py dev logs
python compose.py dev ps
python compose.py dev check
python compose.py dev manage test
python compose.py dev django-shell
python compose.py dev down
```

## Production-like запуск через Docker

Перед production-like запуском задайте безопасные значения:

- `DJANGO_DEBUG=False`;
- `DJANGO_SECRET_KEY` с уникальным секретом;
- `DJANGO_ALLOWED_HOSTS` со списком реальных доменов или IP;
- рабочий `EMAIL_URL`, ведущий на реальный SMTP-сервер, подходящий для массовой отправки email-сообщений;
- при необходимости `LISTEN_PORT`, `DB_*` и `REDIS_PASSWORD`.

Минимальная команда, собирает образ, выполняет миграции, собирает static-файлы и запускает сервисы в фоне:

```powershell
python compose.py prod deploy
```

Runner-скрипт compose.py предоставляет другие полезные команды:

```powershell
python compose.py prod build
python compose.py prod migrate
python compose.py prod collectstatic
python compose.py prod up
python compose.py prod check-deploy
python compose.py prod logs
```

Снаружи приложение доступно через Nginx на порту `LISTEN_PORT`, по умолчанию `8080`.

## Локальный запуск без Docker

Подходит для локальной разработки, но PostgreSQL и Redis нужно запустить отдельно.
Для упрощенного локального режима можно использовать SQLite и
консольную почту `consolemail://` или dummy-заглушку `dummymail://`.

1. Создайте виртуальное окружение и установите зависимости:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

   Для запуска example-скриптов дополнительно установите dev-зависимости:

   ```powershell
   python -m pip install -r requirements.dev.txt
   ```

2. Настройте `.env`. Пример для SQLite и вывода писем в консоль:

   ```env
   DJANGO_SECRET_KEY=local-dev-key
   DJANGO_DEBUG=True
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
   DATABASE_URL=sqlite:///db.sqlite3
   CELERY_BROKER_URL=redis://default:redis_password@localhost:6379/0
   EMAIL_URL=consolemail://
   SQL_TRACE=False
   ```

3. Примените миграции и создайте администратора (при необходимости):

   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   ```

4. Запустите Django:

   ```powershell
   python manage.py runserver 127.0.0.1:8000
   ```

5. В отдельном терминале запустите Celery worker:

   ```powershell
   python manage.py celery
   ```

   Если Celery worker не запущен, API продолжит отвечать, но письма подтверждения,
   сброса пароля и уведомления по заказам не будут отправляться.

## Модель данных

Основные сущности:

- `User` - пользователь с email в качестве логина, расширяет стандартную модель `AbstractUser`;
- `Token` - API-токен, позволяющий иметь несколько активных токенов у одного пользователя;
- `Contact` - адрес доставки и контактные данные для связи с контактным лицом;
- `Shop` - магазин поставщика, привязанный к пользователю, пользователь может иметь не более одного магазина;
- `Category` - категория товаров;
- `Product` - товар как общая карточка с названием и категорией;
- `ShopOffer` - предложение магазина по конкретному товару: артикул, модель, цена, рекомендованная цена, остаток;
- `Parameter` и `ProductParameter` - характеристики товарного предложения;
- `Order` - заказ пользователя либо корзина;
- `Basket` и `PlacedOrder` - proxy-модели для удобной работы с корзинами и оформленными заказами в админке;
- `OrderItem` - позиция заказа, связанная с конкретным `ShopOffer`.

У пользователя может быть только одна активная корзина. Оформленный заказ обязан иметь контакт доставки.
Переходы статусов заказа ограничены сервисным слоем и формами админки.

## Импорт прайсов

Поставщик отправляет URL YAML-файла в `POST /api/v1/partner/update`. Если у пользователя еще нет магазина,
он создается при первом успешном импорте. При повторном импорте название и URL магазина обновляются,
а старые предложения этого магазина заменяются новыми.

Ожидаемый формат YAML:

```yaml
shop: Связной
categories:
  - id: 224
    name: Смартфоны
goods:
  - id: 4216292
    category: 224
    model: apple/iphone/xs-max
    name: Смартфон Apple iPhone XS Max 512GB
    price: 110000
    price_rrc: 116990
    quantity: 14
    parameters:
      "Диагональ (дюйм)": 6.5
      "Цвет": золотистый
```

Валидация проверяет дубли категорий и товаров, положительные числовые значения и наличие категории,
на которую ссылается товар. Примеры корректных файлов лежат в папке `shop_data`. Тестовые `shop_data/dups.yaml`
и `shop_data/invalid_crosslink.yaml` полезны для проверки ошибок валидации, они преднамеренно содержат
типовые ошибки в документе с целью вызвать ошибку.

В `DJANGO_DEBUG=True` можно импортировать локальный файл:

```json
{
  "url": "file:///shop_data/shop01.yaml"
}
```

В production-режиме используйте обычные `http://` или `https://` URL,
обработка URL вида `file://` отключена в целях безопасности.

## API

Все пользовательские методы находятся под префиксом `/api/v1/`. Для методов, меняющих состояние
сущностей либо дающие доступ к персональной информации, требуется явная авторизация:

```http
Authorization: Token <token>
```

Все методы API реализованы совместимыми с предложенным API в формате Postman Collection:
[netology-pd-diplom](https://documenter.getpostman.com/view/5037826/SVfJUrSc)

Для фактической реализации приведённая выше Postman Collection была дополнена:
[netology-pd-diplom-new](https://documenter.getpostman.com/view/46171784/2sBXqKp16P)

Для методов API, возвращающих списки элементов, доступна пагинация limit-offset. Чтобы её активировать,
необходимо передать дополнительные query-параметры `limit` и `offset`.

### Пользователь

| Метод | URL | Назначение |
| --- | --- | --- |
| `POST` | `/api/v1/user/register` | Регистрация пользователя. Аккаунт создается неактивным до подтверждения email. |
| `POST` | `/api/v1/user/register/verify` | Повторный запрос письма подтверждения пользователя. |
| `POST` | `/api/v1/user/register/confirm` | Подтверждение email по токену. |
| `POST` | `/api/v1/user/password_reset` | Запрос письма для сброса пароля пользователя. |
| `POST` | `/api/v1/user/password_reset/confirm` | Подтверждение сброса пароля пользователя по проверочному токену. |
| `POST` | `/api/v1/user/login` | Вход и получение API-токена для доступа к защищённым методам API. |
| `GET` | `/api/v1/user/details` | Получение данных текущего пользователя. |
| `POST` | `/api/v1/user/details` | Частичное обновление данных текущего пользователя. |
| `GET` | `/api/v1/user/contact` | Список контактов пользователя. |
| `POST` | `/api/v1/user/contact` | Создание контакта доставки. |
| `PUT` | `/api/v1/user/contact` | Изменение контакта по `id` в теле запроса. |
| `DELETE` | `/api/v1/user/contact` | Удаление контактов по списку `items`, разделённых запятыми. |

### Каталог и корзина

| Метод | URL | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/shops` | Список активных магазинов. Фильтр: `name`. |
| `GET` | `/api/v1/categories` | Список категорий. Фильтр: `name`. |
| `GET` | `/api/v1/products` | Список товарных предложений. Фильтры: `shop_id`, `category_id`, `part_number`, `search`. |
| `GET` | `/api/v1/basket` | Текущая корзина пользователя. |
| `POST` | `/api/v1/basket` | Добавить указанные позиции в корзину. |
| `PUT` | `/api/v1/basket` | Изменить количество товаров по указанным позициям в корзине. |
| `DELETE` | `/api/v1/basket` | Удалить позиции из корзины по списку `items`, разделённым запятыми. |
| `GET` | `/api/v1/order` | Список оформленных заказов пользователя. |
| `GET` | `/api/v1/order/<id>` | Детали конкретного заказа пользователя с ID=`<id>`. |
| `POST` | `/api/v1/order` | Оформить корзину или переоформить ранее отмененный заказ. |
| `DELETE` | `/api/v1/order/<id>` | Отменить указанный заказ. |

### Поставщик (партнёр)

| Метод | URL | Назначение |
| --- | --- | --- |
| `POST` | `/api/v1/partner/update` | Загрузить или обновить прайс магазина по URL. |
| `GET` | `/api/v1/partner/state` | Получить состояние магазина текущего пользователя. |
| `POST` | `/api/v1/partner/state` | Включить или отключить прием заказов. |
| `GET` | `/api/v1/partner/orders` | Получить заказы, содержащие товары магазина текущего пользователя. |
| `GET` | `/api/v1/partner/orders/<id>` | Получить детали указанного заказа с позициями только от текущего магазина. |

## Примеры запросов

Регистрация:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/user/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test_user@example.com",
    "password": "test_password",
    "first_name": "Кузьма",
    "last_name": "Агафонов"
  }'
```

Подтверждение пользователя (необходимо указать `<verify_token>`,
отправленный на указанный пользователем email-адрес):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/user/register/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test_user@example.com",
    "token": "<verify_token>"
  }'
```

Вход по паролю:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/user/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test_user@example.com",
    "password": "test_password"
  }'
```

Добавление товара в корзину:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/basket \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"product_info": 1, "quantity": 2}
    ]
  }'
```

Оформление заказа:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/order \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"id": 1, "contact": 1}'
```

Обновление прайса магазина (создание либо обновления магазина):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/partner/update \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/shop.yaml"}'
```

## Бизнес-логика заказов

Корзина хранится как заказ со статусом `basket`. При оформлении создается новый заказ
со статусом `new`, позиции переносятся из корзины, а количество в `ShopOffer`
уменьшается на заказанное значение.

### Диаграмма переходов состояния заказа

![Диаграмма переходов состояния заказа](order_state_transitions.png)

Отмена активного заказа возвращает товары на склад. Повторное открытие отмененного
заказа в `new` снова резервирует остатки. Для всех критичных операций используется
транзакция и блокировки строк, чтобы снизить риск гонки данных при одновременном оформлении заказов.

## Django Admin

Административная панель доступна по внутреннему URL `/admin/`. В ней доступны для просмотра и изменения все
бизнес-сущности: зарегистрированы пользователи, токены, контакты, категории, товары, магазины,
предложения, позиции заказов, корзины и оформленные заказы.

### Особенности

- списки оптимизированы через `select_related`, `prefetch_related` и аннотации;
- в административной панели отсутствует возможность напрямую создавать заказы;
- чтобы создать заказ, необходимо нажать кнопку `Checkout basket` для заранее подготовленной корзины;
- у оформленных заказов нельзя напрямую менять позиции активного заказа;
- форма заказа показывает только допустимые варианты для статуса заказа согласно диаграмме переходов выше;
- при смене статуса заказа уведомления отправляются через Celery после успешного commit-а транзакции.

## Email и Celery

Содержимое всех email-писем создаётся из шаблонов в папке `api/templates/api/`.
Для каждого письма есть тема - subject, текстовая версия - text, и, по возможности, HTML-версия.

Celery-задачи:

- `send_user_verification_mail`;
- `send_password_reset_mail`;
- `notify_order_state`.

## Использование проверочных токенов

Данные токены используются при запросе пользователем:

- подтверждения email
- сброса пароля

Особенности:

- для создания токенов используется класс `django.contrib.auth.tokens.PasswordResetTokenGenerator`;
- токен представляет собой хэш-строку из определённых целевых полей модели `User` и текущего времени;
- после первого успешного использования целевые поля модели `User` обновляются;
- токен автоматически становится недействительным после использования;
- срок действия токена определяется настройкой Django `settings.PASSWORD_RESET_TIMEOUT`.

Сохранение проверочных токенов в БД не требуется в силу их природы. При изменении любого поля, которое было
использовано для генерации токена, сам токен больше никогда не пройдёт проверку.

В режиме `DJANGO_DEBUG=True` проверочные токены, которые генерируются по запросу пользователя,
дополнительно включаются в состав ответного JSON, чтобы было возможно автоматизировать
получение проверочных токенов в тестовых сценариях.

## Проверки и тесты

Локально:

```powershell
python manage.py check
python manage.py test
```

Через Docker dev:

```powershell
python compose.py dev check
python compose.py dev manage test
```

## Демонстрационные сценарии

`example_sync.py` и `example_async.py` демонстрируют полный сценарий работы с API:

- создание пользователей;
- создание контактов;
- регистрация магазинов;
- импорт прайсов;
- заполнение корзины;
- оформление заказа;
- отмену заказа;

Перед запуском проверьте константы в начале файла: адрес сервера, email тестового пользователя, источник YAML-файлов и количество создаваемых данных.

```powershell
python -m pip install -r requirements.dev.txt
python example_sync.py
python example_async.py
```
