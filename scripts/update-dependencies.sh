#!/usr/bin/env bash

set -euo pipefail

BOILERPLATES_REPO_ROOT="${BOILERPLATES_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BOILERPLATES_HOST_ROOT="${BOILERPLATES_HOST_ROOT:-${BOILERPLATES_REPO_ROOT}}"

if [[ -n "${DEBUG:-}" ]]; then
  set -x
fi

_ensure_git_identity() {
  local email
  local name

  email=$(git config --get user.email || true)
  name=$(git config --get user.name || true)

  if [[ -z "${email}" && -n "${WODBOT_GIT_EMAIL:-}" ]]; then
    git config --local user.email "${WODBOT_GIT_EMAIL}"
  fi

  if [[ -z "${name}" && -n "${WODBOT_GIT_NAME:-}" ]]; then
    git config --local user.name "${WODBOT_GIT_NAME}"
  fi
}

_current_repo_slug() {
  local url
  local slug

  url=$(git config --get remote.origin.url || true)
  slug="${url#https://}"
  slug="${slug#*@github.com/}"
  slug="${slug#github.com/}"
  slug="${slug#git@github.com:}"
  slug="${slug%.git}"

  if [[ -z "${slug}" || "${slug}" == "${url}" ]]; then
    slug=$(basename "$(pwd)")
  fi

  echo "${slug}"
}

_report_event() {
  local type="${1}"
  local repo="${2}"
  local message="${3}"
  local report_dir

  if [[ -z "${BOILERPLATE_UPDATE_REPORT_FILE:-}" ]]; then
    return 0
  fi

  if [[ -z "${repo}" ]]; then
    repo=$(_current_repo_slug)
  fi

  report_dir=$(dirname "${BOILERPLATE_UPDATE_REPORT_FILE}")
  mkdir -p "${report_dir}"

  if ! jq -nc \
    --arg type "${type}" \
    --arg repo "${repo}" \
    --arg message "${message}" \
    '{
      type: $type,
      repo: $repo,
      message: $message,
      created_at: (now | todateiso8601)
    }' >> "${BOILERPLATE_UPDATE_REPORT_FILE}"; then
    echo >&2 "Failed to write boilerplate update report event"
  fi
}

_git_commit() {
  local repo_dir="${1}"
  local message="${2}"

  (
    cd "${repo_dir}"
    git add -A

    if git diff --cached --quiet; then
      echo "Nothing to commit"
      return 0
    fi

    _ensure_git_identity
    git commit -m "${message}"
  )
}

_boilerplate_config_entry() {
  local name="${1}"

  "${PYTHON:-python3}" "${BOILERPLATES_REPO_ROOT}/scripts/update_config.py" entry "${name}"
}

_boilerplate_changed_files() {
  local repo_dir="${1}"

  {
    git -C "${repo_dir}" diff --name-only
    git -C "${repo_dir}" diff --cached --name-only
    git -C "${repo_dir}" ls-files --others --exclude-standard
  } | sed '/^$/d' | sort -u
}

_assert_only_allowed_boilerplate_changes() {
  local repo_dir="${1}"
  local allowed_changes="${2}"
  local path

  while IFS= read -r path; do
    if ! jq -e --arg path "${path}" 'index($path) != null' <<<"${allowed_changes}" >/dev/null; then
      echo >&2 "Boilerplate dependency update changed unexpected file: ${path}"
      return 1
    fi
  done < <(_boilerplate_changed_files "${repo_dir}")
}

_boilerplate_run() {
  local image="${1}"
  local host_repo_dir="${2}"
  local host_gid
  local host_uid
  shift 2

  host_uid=$(id -u)
  host_gid=$(id -g)

  docker run --rm \
    --entrypoint "" \
    --user "${host_uid}:${host_gid}" \
    -e HOME=/tmp \
    -v "${host_repo_dir}:/workspace" \
    -w /workspace \
    "${image}" \
    "$@"
}

# Wodby Go images pin cache paths under /home/wodby, which is not writable
# when the container runs as the GitHub runner's host UID.
_boilerplate_run_go() {
  local image="${1}"
  local host_repo_dir="${2}"
  shift 2

  _boilerplate_run "${image}" "${host_repo_dir}" \
    env \
    GOCACHE=/tmp/go-build \
    GOMODCACHE=/tmp/go/pkg/mod \
    GOPATH=/tmp/go \
    "$@"
}

_boilerplate_validation_tag() {
  local name="${1}"
  local image="${2}"
  local suffix

  suffix=$(sed -E 's/[^A-Za-z0-9_.-]+/-/g' <<<"${image}")
  echo "wodby-boilerplate-validation:${name}-${suffix}"
}

_boilerplate_build() {
  local name="${1}"
  local profile="${2}"
  local image="${3}"
  local repo_dir="${4}"
  local tag
  local -a args

  tag=$(_boilerplate_validation_tag "${name}" "${image}")
  args=(
    --build-arg "WODBY_BASE_IMAGE=${image}"
    --build-arg "COPY_FROM=."
    --tag "${tag}"
  )

  if [[ "${profile}" == "expressjs" ]]; then
    args+=(--build-arg "COPY_TO=/usr/src/app")
  fi

  docker build "${args[@]}" "${repo_dir}"

  case "${profile}" in
    expressjs)
      docker run --rm "${tag}" node --check server.js
      ;;
    ruby)
      docker run --rm "${tag}" ruby -c config.ru
      ;;
    rails)
      docker run --rm "${tag}" bin/rails zeitwerk:check
      ;;
  esac

  docker image rm "${tag}" >/dev/null
}

_update_uv_boilerplate() {
  local update_image="${1}"
  local host_repo_dir="${2}"

  _boilerplate_run "${update_image}" "${host_repo_dir}" uv lock --upgrade
}

_validate_uv_boilerplate() {
  local name="${1}"
  local profile="${2}"
  local repo_dir="${3}"
  local host_repo_dir="${4}"
  local validation_images="${5}"
  local image

  while IFS= read -r image; do
    _boilerplate_run "${image}" "${host_repo_dir}" uv sync --frozen
    _boilerplate_run "${image}" "${host_repo_dir}" uv run ruff check .

    case "${profile}" in
      django)
        _boilerplate_run "${image}" "${host_repo_dir}" \
          env DJANGO_SECRET_KEY=boilerplate-validation-only \
          uv run python manage.py check
        _boilerplate_run "${image}" "${host_repo_dir}" \
          env DJANGO_SECRET_KEY=boilerplate-validation-only \
          uv run python manage.py test
        ;;
      pytest|python)
        _boilerplate_run "${image}" "${host_repo_dir}" uv run pytest
        ;;
    esac

    _boilerplate_build "${name}" "${profile}" "${image}" "${repo_dir}"
  done < <(jq -r '.[]' <<<"${validation_images}")
}

_update_npm_boilerplate() {
  local update_image="${1}"
  local host_repo_dir="${2}"

  _boilerplate_run "${update_image}" "${host_repo_dir}" \
    npm update --package-lock-only --ignore-scripts
}

_validate_npm_boilerplate() {
  local name="${1}"
  local profile="${2}"
  local repo_dir="${3}"
  local host_repo_dir="${4}"
  local validation_images="${5}"
  local image

  while IFS= read -r image; do
    _boilerplate_run "${image}" "${host_repo_dir}" npm ci

    case "${profile}" in
      expressjs)
        _boilerplate_run "${image}" "${host_repo_dir}" node --check server.js
        _boilerplate_build "${name}" "${profile}" "${image}" "${repo_dir}"
        ;;
      npm-build)
        _boilerplate_run "${image}" "${host_repo_dir}" npm run build
        ;;
    esac
  done < <(jq -r '.[]' <<<"${validation_images}")
}

_update_bundler_boilerplate() {
  local update_image="${1}"
  local host_repo_dir="${2}"

  _boilerplate_run "${update_image}" "${host_repo_dir}" bundle lock --update
}

_validate_bundler_boilerplate() {
  local name="${1}"
  local profile="${2}"
  local repo_dir="${3}"
  local validation_images="${4}"
  local image

  while IFS= read -r image; do
    _boilerplate_build "${name}" "${profile}" "${image}" "${repo_dir}"
  done < <(jq -r '.[]' <<<"${validation_images}")
}

_update_composer_boilerplate() {
  local update_image="${1}"
  local host_repo_dir="${2}"

  # Lock-only updates cannot run project scripts that depend on an installed vendor directory.
  _boilerplate_run "${update_image}" "${host_repo_dir}" \
    composer update --no-install --no-scripts --no-interaction --no-ansi
}

_validate_composer_boilerplate() {
  local name="${1}"
  local host_repo_dir="${2}"
  local validation_images="${3}"
  local image

  while IFS= read -r image; do
    _boilerplate_run "${image}" "${host_repo_dir}" \
      composer install --no-interaction --no-ansi
    if [[ "${name}" == "laravel" ]]; then
      _boilerplate_run "${image}" "${host_repo_dir}" \
        env APP_KEY=boilerplatevalidationkey00000000 \
        vendor/bin/phpunit --do-not-cache-result
    else
      _boilerplate_run "${image}" "${host_repo_dir}" \
        vendor/bin/phpunit --do-not-cache-result
    fi
  done < <(jq -r '.[]' <<<"${validation_images}")
}

_update_go_boilerplate() {
  local update_image="${1}"
  local host_repo_dir="${2}"

  _boilerplate_run_go "${update_image}" "${host_repo_dir}" go get -u ./...
  _boilerplate_run_go "${update_image}" "${host_repo_dir}" go mod tidy
}

_validate_go_boilerplate() {
  local name="${1}"
  local profile="${2}"
  local repo_dir="${3}"
  local host_repo_dir="${4}"
  local validation_images="${5}"
  local image

  while IFS= read -r image; do
    _boilerplate_run_go "${image}" "${host_repo_dir}" go mod verify
    _boilerplate_run_go "${image}" "${host_repo_dir}" go test ./...
    _boilerplate_run_go "${image}" "${host_repo_dir}" go vet ./...
    _boilerplate_build "${name}" "${profile}" "${image}" "${repo_dir}"
  done < <(jq -r '.[]' <<<"${validation_images}")
}

_set_boilerplate_push_origin() {
  local repo_dir="${1}"
  local slug="${2}"

  if [[ -z "${WODBOT_GITHUB_USERNAME:-}" || -z "${WODBOT_GITHUB_PAT:-}" ]]; then
    echo >&2 "WODBOT_GITHUB_USERNAME and WODBOT_GITHUB_PAT are required to push ${slug}"
    return 1
  fi

  git -C "${repo_dir}" remote set-url origin \
    "https://${WODBOT_GITHUB_USERNAME}:${WODBOT_GITHUB_PAT}@github.com/${slug}"
}

_boilerplate_update_failed() {
  local name="${1}"
  local status="${2}"
  local entry
  local slug

  entry=$(_boilerplate_config_entry "${name}" 2>/dev/null || true)
  slug=$(jq -r '.repo // empty' <<<"${entry:-{}}" 2>/dev/null || true)
  slug="${slug:-wodby/${name}-boilerplate}"
  _report_event "failure" "${slug}" "Dependency update failed"
  exit "${status}"
}

update_boilerplate_dependencies() (
  local name="${1}"
  local entry
  local slug
  local ecosystem
  local profile
  local update_image
  local validation_images
  local allowed_changes
  local work_root
  local repo_dir
  local host_repo_dir
  local relative_repo_dir
  local changed_files

  entry=$(_boilerplate_config_entry "${name}") || {
    echo >&2 "Unknown generic boilerplate: ${name}"
    return 1
  }
  slug=$(jq -r '.repo' <<<"${entry}")
  ecosystem=$(jq -r '.ecosystem' <<<"${entry}")
  profile=$(jq -r '.profile' <<<"${entry}")
  update_image=$(jq -r '.update_image' <<<"${entry}")
  validation_images=$(jq -c '.validation_images' <<<"${entry}")
  allowed_changes=$(jq -c '.allowed_changes' <<<"${entry}")

  work_root="${BOILERPLATES_REPO_ROOT}/.boilerplate-work"
  mkdir -p "${work_root}"
  repo_dir=$(mktemp -d "${work_root}/${name}.XXXXXX")
  trap 'rm -rf "${repo_dir}"' EXIT

  relative_repo_dir="${repo_dir#"${BOILERPLATES_REPO_ROOT}/"}"
  host_repo_dir="${BOILERPLATES_HOST_ROOT}/${relative_repo_dir}"

  git clone "https://github.com/${slug}" "${repo_dir}"

  case "${ecosystem}" in
    uv)
      _update_uv_boilerplate "${update_image}" "${host_repo_dir}"
      ;;
    npm)
      _update_npm_boilerplate "${update_image}" "${host_repo_dir}"
      ;;
    bundler)
      _update_bundler_boilerplate "${update_image}" "${host_repo_dir}"
      ;;
    composer)
      _update_composer_boilerplate "${update_image}" "${host_repo_dir}"
      ;;
    go)
      _update_go_boilerplate "${update_image}" "${host_repo_dir}"
      ;;
    *)
      echo >&2 "Unsupported boilerplate ecosystem: ${ecosystem}"
      return 1
      ;;
  esac

  _assert_only_allowed_boilerplate_changes "${repo_dir}" "${allowed_changes}"
  changed_files=$(_boilerplate_changed_files "${repo_dir}")

  if [[ -z "${changed_files}" ]]; then
    echo "${slug}: dependencies are already current within configured constraints"
    return 0
  fi

  case "${ecosystem}" in
    uv)
      _validate_uv_boilerplate "${name}" "${profile}" "${repo_dir}" \
        "${host_repo_dir}" "${validation_images}"
      ;;
    npm)
      _validate_npm_boilerplate "${name}" "${profile}" "${repo_dir}" \
        "${host_repo_dir}" "${validation_images}"
      ;;
    bundler)
      _validate_bundler_boilerplate "${name}" "${profile}" "${repo_dir}" \
        "${validation_images}"
      ;;
    composer)
      _validate_composer_boilerplate "${name}" "${host_repo_dir}" \
        "${validation_images}"
      ;;
    go)
      _validate_go_boilerplate "${name}" "${profile}" "${repo_dir}" \
        "${host_repo_dir}" "${validation_images}"
      ;;
  esac

  _assert_only_allowed_boilerplate_changes "${repo_dir}" "${allowed_changes}"

  if [[ "${BOILERPLATE_UPDATE_PUSH:-0}" != "1" ]]; then
    git -C "${repo_dir}" diff --stat
    _report_event "validated" "${slug}" "Compatible dependency updates validated without push"
    return 0
  fi

  _set_boilerplate_push_origin "${repo_dir}" "${slug}"
  _git_commit "${repo_dir}" "Update dependencies"
  git -C "${repo_dir}" push origin
  _report_event "commit" "${slug}" "Update dependencies"
)

main() {
  local boilerplate="${1:-}"
  local status

  if [[ -z "${boilerplate}" ]]; then
    echo >&2 "Boilerplate name is required"
    return 1
  fi

  set +e
  (
    set -e
    update_boilerplate_dependencies "${boilerplate}"
  )
  status=$?
  set -e

  if [[ "${status}" != "0" ]]; then
    _boilerplate_update_failed "${boilerplate}" "${status}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
