#!/usr/bin/env bash
# backup-rotation.sh — backup.sh / restore.sh 共用的备份轮转与校验辅助函数。
#
# 本文件是共享库，被脚本 source，不直接执行；运行环境需满足 `set -euo pipefail`。
# 仅在调用 rotate_* 函数时才会产生删除副作用，且删除只发生在调用方传入的目录内。
#
# 轮转默认值与 docs/deployment.md:246 建议一致（每日 30 / 每月 12），均可通过环境变量覆盖：
#   BACKUP_KEEP_DAILY       日备保留份数（默认 30）
#   BACKUP_KEEP_MONTHLY     月备保留份数（默认 12，每个日历月保留最新一份）
#   BACKUP_KEEP_PRE_RESTORE pre-restore 快照保留份数（默认 20）
#
# 与迁移前快照的关系：backend/app/db.py 的 _backup_before_migrate() 保留
# agvpm-before-migrate-* 最近 20 份的逻辑不在本文件处理（保持不变）；
# 本文件只轮转 agv-pm-*.tar.gz（普通备份）与 agvpm-pre-restore-*（恢复前快照）。

# 单文件 sha256（兼容 Linux sha256sum 与 macOS shasum -a 256），仅输出 hash。
sha256_of() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    shasum -a 256 "$file" | awk '{print $1}'
  fi
}

# rotate_backups DIR — 轮转 DIR 下的 agv-pm-*.tar.gz。
# 保留集合 = 最近 BACKUP_KEEP_DAILY 份 + 最近 BACKUP_KEEP_MONTHLY 个不同月份各自最新一份；
# 其余旧包（连同 .sha256 侧车文件）删除。文件名内嵌 %Y%m%d-%H%M%S 时间戳，字典序即时间序。
rotate_backups() {
  local dir="$1"
  local keep_daily="${BACKUP_KEEP_DAILY:-30}"
  local keep_monthly="${BACKUP_KEEP_MONTHLY:-12}"
  local stamp_re='[0-9]{8}-[0-9]{6}'
  local all_file keep_file f month seen=""
  local -a all=() keep=()
  local i count=0 month_count=0

  all_file="$(mktemp)"
  keep_file="$(mktemp)"
  find "$dir" -maxdepth 1 -type f -name 'agv-pm-*.tar.gz.agvenc' -print | sort > "$all_file"
  # 仅时间戳文件参与保留判定：无时间戳的 agv-pm-* 文件（如手工放置的包）一律跳过，
  # 既不占用日/月保留名额，也绝不在轮转中删除（HYPE-52 返工项 1）。
  while IFS= read -r f; do
    if basename "$f" | grep -qE "$stamp_re"; then
      all+=("$f")
    fi
  done < "$all_file"
  if [ "${#all[@]}" -eq 0 ]; then
    rm -f "$all_file" "$keep_file"
    return 0
  fi

  # 月保留：从最新往回扫，每个不同月份取最新一份，最多 keep_monthly 个月。
  for ((i = ${#all[@]} - 1; i >= 0; i--)); do
    f="${all[$i]}"
    month="$(basename "$f" | grep -oE "$stamp_re" | head -1 | cut -c1-6)"
    [ -n "$month" ] || continue
    case " $seen " in
      *" $month "*) continue ;;
    esac
    seen="$seen $month"
    keep+=("$f")
    month_count=$((month_count + 1))
    [ "$month_count" -ge "$keep_monthly" ] && break
  done

  # 日保留：最近 keep_daily 份。
  count=0
  for ((i = ${#all[@]} - 1; i >= 0; i--)); do
    f="${all[$i]}"
    count=$((count + 1))
    keep+=("$f")
    [ "$count" -ge "$keep_daily" ] && break
  done

  printf '%s\n' "${keep[@]}" | sort -u > "$keep_file"
  for f in "${all[@]}"; do
    if ! grep -Fxq "$f" "$keep_file"; then
      rm -f -- "$f" "$f.sha256"
      echo "  轮转删除旧备份: $(basename "$f")"
    fi
  done
  rm -f "$all_file" "$keep_file"
}

# rotate_pre_restore DIR — 轮转 DIR 下的 agvpm-pre-restore-* 快照，保留最近 BACKUP_KEEP_PRE_RESTORE 份。
rotate_pre_restore() {
  local dir="$1"
  local keep="${BACKUP_KEEP_PRE_RESTORE:-20}"
  local stamp_re='[0-9]{8}-[0-9]{6}'
  local f
  local -a all=()
  local i count=0
  # 与 rotate_backups 一致：仅时间戳快照参与保留判定，无时间戳文件安全跳过、不删除。
  while IFS= read -r f; do
    if basename "$f" | grep -qE "$stamp_re"; then
      all+=("$f")
    fi
  done < <(find "$dir" -maxdepth 1 -type f -name 'agvpm-pre-restore-*.agvenc' -print | sort)
  for ((i = ${#all[@]} - 1; i >= 0; i--)); do
    f="${all[$i]}"
    count=$((count + 1))
    if [ "$count" -gt "$keep" ]; then
      rm -f -- "$f" "$f.sha256"
      echo "  轮转删除旧 pre-restore 快照: $(basename "$f")"
    fi
  done
}
