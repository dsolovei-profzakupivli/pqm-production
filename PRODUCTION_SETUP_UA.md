# PQM — production setup

## Архітектура

- Render Web Service, 1 instance.
- Docker / Python 3.12.
- Persistent SSD disk `/var/data`.
- SQLite залишається на першому production етапі, щоб не переписувати великий існуючий SQL-код PQM на PostgreSQL до стабілізації вебверсії.
- HTTPS завершується на Render.
- Basic Auth + серверна роль: `viewer`, `officer`, `admin`.
- Google OAuth використовується тільки для окремих інтеграцій із Google Sheets/Drive.
- ProzorroBids залишається окремим сховищем і не входить у базовий deployment.

## Чому SQLite + persistent disk, а не PostgreSQL зараз

Поточний PQM використовує значний обсяг SQLite-специфічного SQL, WAL і окрему велику локальну базу ProzorroBids. Перехід на PostgreSQL — окремий етап міграції. Для першого бойового запуску безпечніше зберегти існуючу модель і запускати один екземпляр.

## Render

1. Створіть приватний GitHub repository.
2. Завантажте весь вміст цього каталогу в root repository.
3. У Render оберіть **New → Blueprint** і підключіть repository.
4. Render прочитає `render.yaml`.
5. Переконайтеся, що service `pqm-production` має paid `starter` plan і persistent disk 10 GB.
6. У Environment додайте `PQM_USERS_JSON`.
7. Для Google OAuth завантажте OAuth client JSON як secret file і вкажіть шлях у `PQM_GOOGLE_OAUTH_CLIENT`.
8. Deploy.

## Створення користувачів

Для кожного користувача створіть PBKDF2 hash:

```bash
python tools/make_password_hash.py
```

Потім сформуйте JSON, наприклад:

```json
{
  "admin": {
    "name": "Адміністратор",
    "role": "admin",
    "password_hash": "pbkdf2_sha256$..."
  },
  "officer": {
    "name": "УО",
    "role": "officer",
    "password_hash": "pbkdf2_sha256$..."
  },
  "viewer": {
    "name": "Перегляд",
    "role": "viewer",
    "password_hash": "pbkdf2_sha256$..."
  }
}
```

Не зберігайте цей JSON у Git.

## Google OAuth

Google OAuth client має дозволяти callback:

`https://YOUR-DOMAIN/api/google-oauth/callback`

Для першого запуску краще використовувати окремий production OAuth client, а не локальний client.

## Домен

Після першого deploy у Render додайте production custom domain. Render видає TLS/HTTPS для custom domain.

## Перенесення локальної БД

Не копіюйте `data/pqm.sqlite3` у Git.

Для контрольованого перенесення використовуйте SQLite backup/restore через Render Shell або окремий імпорт. Поточна локальна БД є тестовою і містить ручні рішення, протоколи та інші локальні зміни, які за журналом PQM не повинні автоматично ставати production-даними.

## ProzorroBids

Модуль «Закупівлі за відборами» очікує окрему велику базу. Якщо її не змонтувати у `/var/data/prozorro_bids.db`, модуль буде недоступний, але основний PQM продовжить працювати.

## Backup

Render persistent disks мають автоматичні daily snapshots. Додатково можна запускати `backup_sqlite.py` вручну перед великими міграціями.

## Після deploy

Перевірити:

- `/api/health` → HTTP 200;
- Basic Auth → admin/officer/viewer;
- список заявок;
- редагування заявки під officer;
- блокування viewer;
- формування DOCX;
- синхронізацію Prozorro;
- НАЗК/АМКУ;
- Google OAuth;
- завантаження архіву заявки;
- журнал аудиту.

## Важливе обмеження

Persistent disk прив'язаний до одного service instance. Тому `numInstances: 1` є навмисним. Горизонтальне масштабування можливе лише після міграції робочої БД і файлового сховища на зовнішні managed services.
