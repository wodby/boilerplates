# Wodby boilerplates

This repository indexes the application boilerplates exposed by Wodby service
build configuration. It maps each boilerplate to the service manifests that
make it available in the Wodby UI.

[`boilerplates.yml`](boilerplates.yml) is the machine-readable catalog. A
service reference records the service repository, manifest path, template name,
branch or tag constraint, and optional pipeline file.

Wodby-managed boilerplate dependency updates run from this repository. Generic
update and validation profiles and specialized Drupal and WordPress upstream
synchronizers live beside the service catalog in
[`boilerplates.yml`](boilerplates.yml). External upstream templates are
cataloged because services expose them, but Wodby does not update their
repositories.

## Wodby-managed boilerplates

| Boilerplate | Dependency updates | Services |
| --- | --- | --- |
| [Django](https://github.com/wodby/django-boilerplate) | Generic | [`service-django`](https://github.com/wodby/service-django) |
| [Drupal CMS](https://github.com/wodby/drupal-cms-template) | Specialized | [`service-drupal-php`](https://github.com/wodby/service-drupal-php) (`11/service.yml`) |
| [Vanilla Drupal](https://github.com/wodby/drupal-vanilla) | Specialized | [`service-drupal-php`](https://github.com/wodby/service-drupal-php) (`10/service.yml`, `11/service.yml`) |
| [Express.js](https://github.com/wodby/expressjs-boilerplate) | Generic | [`service-node`](https://github.com/wodby/service-node) |
| [FastAPI](https://github.com/wodby/fastapi-boilerplate) | Generic | [`service-fastapi`](https://github.com/wodby/service-fastapi) |
| [Flask](https://github.com/wodby/flask-boilerplate) | Generic | [`service-flask`](https://github.com/wodby/service-flask) |
| [Go](https://github.com/wodby/go-boilerplate) | Generic | [`service-go`](https://github.com/wodby/service-go) |
| [Next.js](https://github.com/wodby/nextjs-boilerplate) | Generic | [`service-httpd`](https://github.com/wodby/service-httpd), [`service-nextjs`](https://github.com/wodby/service-nextjs) |
| [Composer package](https://github.com/wodby/php-package-boilerplate) | Generic | [`service-php`](https://github.com/wodby/service-php) |
| [Python](https://github.com/wodby/python-boilerplate) | Generic | [`service-python`](https://github.com/wodby/service-python) |
| [Rails](https://github.com/wodby/rails-boilerplate) | Generic | [`service-rails`](https://github.com/wodby/service-rails) |
| [React](https://github.com/wodby/react-boilerplate) | Generic | [`service-nginx`](https://github.com/wodby/service-nginx) |
| [Ruby](https://github.com/wodby/ruby-boilerplate) | Generic | [`service-ruby`](https://github.com/wodby/service-ruby) |
| [Vanilla WordPress](https://github.com/wodby/wordpress-vanilla) | Specialized | [`service-wordpress-php`](https://github.com/wodby/service-wordpress-php) |

## External upstream templates

| Template | Services | Reference |
| --- | --- | --- |
| [Laravel](https://github.com/laravel/laravel) | [`service-laravel-php`](https://github.com/wodby/service-laravel-php) | `^13` |
| [Matomo](https://github.com/matomo-org/matomo) | [`service-matomo`](https://github.com/wodby/service-matomo) | `^5` |

## Validation

The validation workflow compares the catalog with every `build.templates`
entry in the managed services listed by [`wodby/services`](https://github.com/wodby/services).
It fails when a service template is missing from this catalog, when a stale
consumer remains, or when repository, ref, or pipeline metadata differs.

Run it locally with:

```bash
python3 -m pip install pyyaml requests
python3 scripts/validate.py
```

## Dependency updates

The scheduled update workflow refreshes compatible dependency lockfiles and
accepts generic changes only to the files declared in `allowed_changes`. It
validates each generic update against the oldest and newest supported Wodby
runtime images before pushing directly to the boilerplate repository's default
branch. Specialized jobs synchronize the Drupal 11, Drupal 10, Drupal 7, Drupal
CMS 2, and WordPress templates with their upstream sources. Manifest
constraints and major dependency lines remain manual.

Run a single update locally without pushing:

```bash
python3 -m pip install pyyaml
scripts/update-dependencies.sh rails
```

Set `BOILERPLATE_UPDATE_PUSH=1` together with the Git machine-user credentials
used by the workflow only when the validated update should be committed and
pushed.

The workflow uploads a consolidated JSON and Markdown report and sends an email
digest only when dependency updates, failures, or report warnings are present.
Configure the same repository secrets used by the Wodby services and images
report workflows:

- `REPORT_EMAIL_TO` (required; comma- or semicolon-separated recipients)
- `REPORT_EMAIL_FROM` (required unless `SMTP_USERNAME` is the sender)
- `SMTP_HOST` (required)
- `SMTP_PORT` (optional; defaults to `587`)
- `SMTP_USERNAME` and `SMTP_PASSWORD` (optional for relays without authentication)
- `SMTP_SSL` (optional; defaults to disabled)
- `SMTP_STARTTLS` (optional; defaults to enabled)
