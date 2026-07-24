#!/usr/bin/env bash

set -euo pipefail

BOILERPLATES_REPO_ROOT="${BOILERPLATES_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SPECIALIZED_WORK_ROOT=""

if [[ -n "${DEBUG:-}" ]]; then
  set -x
fi

_report_event() {
  local type="${1}"
  local repo="${2}"
  local message="${3}"
  local report_dir

  if [[ -z "${BOILERPLATE_UPDATE_REPORT_FILE:-}" ]]; then
    return 0
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
    echo >&2 "Failed to write specialized boilerplate update report event"
  fi
}

_specialized_repo() {
  case "${1}" in
    drupal-cms)
      echo "wodby/drupal-cms-template"
      ;;
    drupal-vanilla)
      echo "wodby/drupal-vanilla"
      ;;
    wordpress-vanilla)
      echo "wodby/wordpress-vanilla"
      ;;
    *)
      return 1
      ;;
  esac
}

_ensure_git_identity() {
  local repo_dir="${1}"

  if [[ -z "$(git -C "${repo_dir}" config --get user.email || true)" && -n "${GIT_USER_EMAIL:-}" ]]; then
    git -C "${repo_dir}" config --local user.email "${GIT_USER_EMAIL}"
  fi
  if [[ -z "$(git -C "${repo_dir}" config --get user.name || true)" && -n "${GIT_USER_NAME:-}" ]]; then
    git -C "${repo_dir}" config --local user.name "${GIT_USER_NAME}"
  fi
}

_git_clone() {
  local slug="${1}"
  local target="${2}"

  git clone "https://github.com/${slug}" "${target}"
}

_set_push_origin() {
  local repo_dir="${1}"
  local slug="${2}"

  if [[ -z "${GITHUB_MACHINE_USER:-}" || -z "${GITHUB_MACHINE_USER_API_TOKEN:-}" ]]; then
    echo >&2 "GitHub machine credentials are required to push ${slug}"
    return 1
  fi

  git -C "${repo_dir}" remote set-url origin \
    "https://${GITHUB_MACHINE_USER}:${GITHUB_MACHINE_USER_API_TOKEN}@github.com/${slug}"
}

_commit_and_publish() {
  local repo_dir="${1}"
  local slug="${2}"
  local message="${3}"
  local branch

  git -C "${repo_dir}" add -A
  if git -C "${repo_dir}" diff --cached --quiet; then
    echo "${slug}: nothing to commit"
    return 0
  fi

  _ensure_git_identity "${repo_dir}"
  git -C "${repo_dir}" commit -m "${message}"

  if [[ "${BOILERPLATE_UPDATE_PUSH:-0}" != "1" ]]; then
    _report_event "validated" "${slug}" "${message} validated without push"
    return 0
  fi

  _set_push_origin "${repo_dir}" "${slug}"
  branch=$(git -C "${repo_dir}" branch --show-current)
  git -C "${repo_dir}" push origin "HEAD:${branch}"
  _report_event "commit" "${slug}" "${message}"
}

_install_composer() {
  local installer_dir
  local expected_checksum
  local actual_checksum

  if command -v composer >/dev/null; then
    return 0
  fi

  apk add --no-cache php-cli php-openssl php-phar php-mbstring ca-certificates
  installer_dir=$(mktemp -d)

  if ! (
    cd "${installer_dir}"
    expected_checksum=$(php -r 'copy("https://composer.github.io/installer.sig", "php://stdout");')
    php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
    actual_checksum=$(php -r "echo hash_file('sha384', 'composer-setup.php');")
    if [[ "${expected_checksum}" != "${actual_checksum}" ]]; then
      echo >&2 "Composer installer checksum verification failed"
      exit 1
    fi
    php composer-setup.php --install-dir=/usr/local/bin --filename=composer
  ); then
    rm -rf "${installer_dir}"
    return 1
  fi

  rm -rf "${installer_dir}"
}

_assert_all_entries_copied() {
  local source_dir="${1}"
  local target_dir="${2}"
  local -a missing_entries=()
  local entry
  local name

  while IFS= read -r entry; do
    name="${entry##*/}"
    if [[ "${name}" == .* ]] || [[ "${name}" == *.md ]] || [[ "${name}" == *.txt ]]; then
      continue
    fi
    if [[ ! -e "${target_dir}/${name}" ]]; then
      missing_entries+=("${name}")
    fi
  done < <(find "${source_dir}" -mindepth 1 -maxdepth 1 | sort)

  if [[ "${#missing_entries[@]}" -gt 0 ]]; then
    echo >&2 "Failed to copy upstream entries: ${missing_entries[*]}"
    return 1
  fi
}

_update_drupal_vanilla() {
  local work_root="${1}"
  local target="${work_root}/drupal-vanilla"
  local recommended="${work_root}/recommended-project"
  local legacy="${work_root}/drupal-project"
  local latest_ver

  echo "Updating Drupal 11"
  _git_clone "wodby/drupal-vanilla" "${target}"
  _git_clone "drupal/recommended-project" "${recommended}"
  _install_composer
  latest_ver=$(git -C "${recommended}" tag --list '11.*' | grep -P '^11\.[0-9]+\.[0-9]+$' | sort -rV | head -n1 || true)
  if [[ -z "${latest_ver}" ]]; then
    echo >&2 "Failed to detect latest Drupal 11 version"
    return 1
  fi
  git -C "${recommended}" checkout "${latest_ver}"
  cp "${recommended}/composer.json" "${recommended}/composer.lock" "${target}"
  (
    cd "${target}"
    composer require --dev drush/drush --no-install --ignore-platform-reqs --no-security-blocking
  )
  _commit_and_publish "${target}" "wodby/drupal-vanilla" "Update Drupal 11"

  echo "Updating Drupal 10"
  git -C "${target}" checkout 10.x
  latest_ver=$(git -C "${recommended}" tag --list '10.*' | grep -P '^10\.[0-9]+\.[0-9]+$' | sort -rV | head -n1 || true)
  if [[ -z "${latest_ver}" ]]; then
    echo >&2 "Failed to detect latest Drupal 10 version"
    return 1
  fi
  git -C "${recommended}" checkout "${latest_ver}"
  cp "${recommended}/composer.json" "${recommended}/composer.lock" "${target}"
  (
    cd "${target}"
    composer require --dev drush/drush --no-install --ignore-platform-reqs --no-security-blocking
  )
  _commit_and_publish "${target}" "wodby/drupal-vanilla" "Update Drupal 10"

  echo "Updating Drupal 7"
  git -C "${target}" checkout 7.x
  _git_clone "drupal-composer/drupal-project" "${legacy}"
  git -C "${legacy}" checkout 7.x
  cp -R "${legacy}/composer.json" "${legacy}/drush" "${legacy}/scripts" "${legacy}/phpunit.xml.dist" "${target}"
  _commit_and_publish "${target}" "wodby/drupal-vanilla" "Update Drupal 7"
}

_update_wordpress_vanilla() {
  local work_root="${1}"
  local target="${work_root}/wordpress-vanilla"

  echo "Updating WordPress"
  _git_clone "wodby/wordpress-vanilla" "${target}"
  _install_composer
  (
    cd "${target}"
    composer update --no-install --ignore-platform-reqs
  )
  _commit_and_publish "${target}" "wodby/wordpress-vanilla" "Update WordPress"
}

_update_drupal_cms() {
  local work_root="${1}"
  local target="${work_root}/drupal-cms-template"
  local upstream="${work_root}/cms"
  local latest_ver

  echo "Updating Drupal CMS 2.x template"
  _git_clone "wodby/drupal-cms-template" "${target}"
  git clone "https://git.drupalcode.org/project/cms.git" "${upstream}"
  latest_ver=$(git -C "${upstream}" tag --list '2.*' | grep -P '^2\.[0-9]+\.[0-9]+$' | sort -rV | head -n1 || true)
  if [[ -z "${latest_ver}" ]]; then
    echo >&2 "Failed to detect latest Drupal CMS 2 version"
    return 1
  fi
  git -C "${upstream}" checkout "${latest_ver}"
  cp -R "${upstream}/assets" "${upstream}/config" "${upstream}/composer.json" "${target}"
  _assert_all_entries_copied "${upstream}" "${target}"
  _install_composer
  (
    cd "${target}"
    composer update --no-install --ignore-platform-reqs --no-security-blocking
  )
  _commit_and_publish "${target}" "wodby/drupal-cms-template" "Update Drupal CMS 2.x"
}

update_specialized_boilerplate() {
  local name="${1}"

  SPECIALIZED_WORK_ROOT=$(mktemp -d)
  trap 'rm -rf "${SPECIALIZED_WORK_ROOT}"' EXIT

  case "${name}" in
    drupal-cms)
      _update_drupal_cms "${SPECIALIZED_WORK_ROOT}"
      ;;
    drupal-vanilla)
      _update_drupal_vanilla "${SPECIALIZED_WORK_ROOT}"
      ;;
    wordpress-vanilla)
      _update_wordpress_vanilla "${SPECIALIZED_WORK_ROOT}"
      ;;
    *)
      echo >&2 "Unknown specialized boilerplate: ${name}"
      return 1
      ;;
  esac
}

main() {
  local name="${1:-}"
  local repo
  local status

  if [[ -z "${name}" ]]; then
    echo >&2 "Specialized boilerplate name is required"
    return 1
  fi
  repo=$(_specialized_repo "${name}") || {
    echo >&2 "Unknown specialized boilerplate: ${name}"
    return 1
  }

  set +e
  (
    set -e
    update_specialized_boilerplate "${name}"
  )
  status=$?
  set -e

  if [[ "${status}" != "0" ]]; then
    _report_event "failure" "${repo}" "Specialized dependency update failed"
    return "${status}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
