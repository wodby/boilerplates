#!/usr/bin/env bash

set -euo pipefail

BOILERPLATES_REPO_ROOT="${BOILERPLATES_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SPECIALIZED_WORK_ROOT=""

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/git_identity.sh"

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
  configure_wodbot_git_identity "${1}"
}

_git_clone() {
  local slug="${1}"
  local target="${2}"

  git clone "https://github.com/${slug}" "${target}"
}

_set_push_origin() {
  local repo_dir="${1}"
  local slug="${2}"

  if [[ -z "${WODBOT_GITHUB_USERNAME:-}" || -z "${WODBOT_GITHUB_PAT:-}" ]]; then
    echo >&2 "WODBOT_GITHUB_USERNAME and WODBOT_GITHUB_PAT are required to push ${slug}"
    return 1
  fi

  git -C "${repo_dir}" remote set-url origin \
    "https://${WODBOT_GITHUB_USERNAME}:${WODBOT_GITHUB_PAT}@github.com/${slug}"
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

_mirror_upstream_entries() {
  local source_dir="${1}"
  local target_dir="${2}"
  local -n keep_entries="${3}"
  local -n skip_entries="${4}"
  local entry
  local name

  # Remove what upstream no longer has, except the files the template owns.
  while IFS= read -r entry; do
    name="${entry##*/}"
    if [[ " ${keep_entries[*]} " == *" ${name} "* ]]; then
      continue
    fi
    if [[ ! -e "${source_dir}/${name}" ]]; then
      echo "Removing ${name}, which upstream no longer has"
      rm -rf "${entry}"
    fi
  done < <(find "${target_dir}" -mindepth 1 -maxdepth 1 | sort)

  # Replace every other entry with upstream's copy, so changes deeper in the tree arrive too.
  while IFS= read -r entry; do
    name="${entry##*/}"
    if [[ " ${keep_entries[*]} " == *" ${name} "* ]] || [[ " ${skip_entries[*]} " == *" ${name} "* ]]; then
      continue
    fi
    rm -rf "${target_dir:?}/${name}"
    cp -R "${entry}" "${target_dir}/${name}"
  done < <(find "${source_dir}" -mindepth 1 -maxdepth 1 | sort)
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
    # WordPress majors are ordinary releases, not breaking changes, so follow the latest one: a caret constraint alone
    # would keep the boilerplate on its old major forever.
    latest_major=$(composer show --all --format=json roots/wordpress-no-content | php -r '
      $versions = array_filter(json_decode(stream_get_contents(STDIN), true)["versions"] ?? [],
        fn ($v) => preg_match("/^[0-9]+\.[0-9]+(\.[0-9]+)?$/", $v));
      usort($versions, "version_compare");
      echo explode(".", (string) end($versions))[0];')
    if [[ -z "${latest_major}" ]]; then
      echo >&2 "Failed to detect the latest WordPress major version"
      exit 1
    fi
    composer require --no-update "roots/wordpress-no-content:^${latest_major}.0"
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
  # The template is upstream's project template plus Wodby's build files: mirror upstream, additions and removals
  # included, and keep the template's own README, build pipeline, Docker ignore file and lock file. DDEV configuration
  # and upstream's contribution guide do not apply to the template.
  local -a template_owned=(.git .wodby .dockerignore README.md composer.lock)
  local -a upstream_skipped=(.git .ddev CONTRIBUTING.md)
  _mirror_upstream_entries "${upstream}" "${target}" template_owned upstream_skipped
  printf '\n# Editors\n.idea\n' >> "${target}/.gitignore"
  _install_composer
  (
    cd "${target}"
    # The Drupal CMS installer downloads the chosen site template while it installs, which needs a writable code base.
    # A Wodby build bakes the code into a read-only image, so the installer finds no template and cannot continue.
    # Ship the two templates it lists first, at the release line of Drupal CMS itself.
    composer require --no-update \
      "drupal/drupal_cms_blank:^${latest_ver%%.*}" \
      "drupal/drupal_cms_starter:^${latest_ver%%.*}"
    # Resolve for the lowest PHP version the Drupal 11 service offers, so every option can install the lock file.
    composer config platform.php 8.3.0
    composer update --no-install --ignore-platform-req='ext-*' --no-security-blocking
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
