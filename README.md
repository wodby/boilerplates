# Wodby boilerplates

This repository indexes the application boilerplates exposed by Wodby service
build configuration. It maps each boilerplate to the service manifests that
make it available in the Wodby UI.

[`boilerplates.yml`](boilerplates.yml) is the machine-readable catalog. A
service reference records the service repository, manifest path, template name,
branch or tag constraint, and optional pipeline file.

Wodby-managed boilerplate dependency updates run from
[`wodby/images`](https://github.com/wodby/images). Generic entries share the
declarative dependency updater; specialized entries have dedicated update
jobs. External upstream templates are cataloged because services expose them,
but Wodby does not update their repositories.

## Wodby-managed boilerplates

| Boilerplate | Dependency updates | Services |
| --- | --- | --- |
| [Django](https://github.com/wodby/django-boilerplate) | Generic | [`service-django`](https://github.com/wodby/service-django) |
| [Drupal CMS](https://github.com/wodby/drupal-cms-template) | Specialized | [`service-drupal-php`](https://github.com/wodby/service-drupal-php) (`11/service.yml`) |
| [Vanilla Drupal](https://github.com/wodby/drupal-vanilla) | Specialized | [`service-drupal-php`](https://github.com/wodby/service-drupal-php) (`10/service.yml`, `11/service.yml`) |
| [Express.js](https://github.com/wodby/expressjs-boilerplate) | Generic | [`service-node`](https://github.com/wodby/service-node) |
| [FastAPI](https://github.com/wodby/fastapi-boilerplate) | Generic | [`service-fastapi`](https://github.com/wodby/service-fastapi) |
| [Flask](https://github.com/wodby/flask-boilerplate) | Generic | [`service-flask`](https://github.com/wodby/service-flask) |
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
| [Laravel](https://github.com/laravel/laravel) | [`service-laravel-php`](https://github.com/wodby/service-laravel-php) | `^11` |
| [Matomo](https://github.com/matomo-org/matomo) | [`service-matomo`](https://github.com/wodby/service-matomo) | `^5` |

## Validation

The validation workflow compares the catalog with every `build.templates`
entry in the managed services listed by [`wodby/services`](https://github.com/wodby/services).
It fails when a service template is missing from this catalog, when a stale
consumer remains, or when repository, ref, or pipeline metadata differs.

Run it locally with:

```bash
python -m pip install pyyaml requests
python scripts/validate.py
```
