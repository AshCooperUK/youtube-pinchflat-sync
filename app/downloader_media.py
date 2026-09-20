"""Filesystem and optional-sidecar handling for native downloads."""
from pathlib import Path
import re
import unicodedata

import yt_dlp


SUBTITLE_EXTENSIONS = {"vtt", "srt", "ass", "ssa", "ttml", "dfxp", "srv1", "srv2", "srv3", "json3", "lrc"}


def safe_media_component(value, max_bytes=180, fallback="YouTube"):
    """Keep Unicode names readable on Linux, SMB shares and Windows."""
    value = unicodedata.normalize("NFC", str(value or ""))
    # yt-dlp substitutes full-width punctuation on Linux. Treat these versions
    # consistently when adopting a folder created by an older release.
    for char in '<>:"/\\|?*':
        value = value.replace(chr(ord(char) + 0xFEE0), char)
    value = value.replace("\u29f8", "/").replace("\u29f9", "\\")
    value = "".join(" " if unicodedata.category(char) in {"Cc", "Cs"} else char for char in value)
    value = re.sub(r'[<>:"/\\|?*]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value.encode("utf-8")[:max_bytes].decode("utf-8", "ignore").rstrip(" .") or fallback
    if re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", value):
        value = "_" + value
    return value


class MediaYoutubeDL(yt_dlp.YoutubeDL):
    """Leave video errors fatal, but allow missing optional subtitle tracks."""

    def __init__(self, params, *, output_root, sidecar_notice=None):
        self.output_root = Path(output_root).resolve()
        self.sidecar_notice = sidecar_notice
        super().__init__({**params, "windowsfilenames": True})

    def prepare_filename(self, info_dict, dir_type="", *, outtmpl=None, warn=False):
        # Work on a copy. Emby and the dashboard retain the original titles.
        info = dict(info_dict)
        for key, limit in (("title", 180), ("uploader", 80), ("channel", 80), ("creator", 80)):
            if info.get(key):
                info[key] = safe_media_component(info[key], limit)
        filename = super().prepare_filename(info, dir_type, outtmpl=outtmpl, warn=warn)
        if not filename:
            return filename
        path = Path(filename)
        if not path.is_absolute():
            path = self.output_root / path
        try:
            relative = path.relative_to(self.output_root)
        except ValueError as exc:
            raise ValueError("Download output must stay inside its configured download folder.") from exc
        if ".." in relative.parts:
            raise ValueError("Download output must stay inside its configured download folder.")
        path = self.output_root.joinpath(*(safe_media_component(part, 240) for part in relative.parts))
        if self.output_root not in path.resolve().parents:
            raise ValueError("Download output must stay inside its configured download folder.")
        return str(path)

    def _write_subtitles(self, info_dict, filename):
        # Scope yt-dlp's optional-error behaviour to subtitles only. Setting
        # ignoreerrors on the whole download would conceal real media failures.
        previous = self.params.get("ignoreerrors")
        self.params["ignoreerrors"] = True
        try:
            result = super()._write_subtitles(info_dict, filename)
        finally:
            self.params["ignoreerrors"] = previous
        requested = info_dict.get("requested_subtitles") or {}
        missing = [lang for lang, sub in requested.items() if not sub.get("filepath") or not Path(sub["filepath"]).is_file()]
        if missing:
            # Embedding must not try to open failed or missing subtitle files.
            info_dict["requested_subtitles"] = {lang: sub for lang, sub in requested.items() if lang not in missing}
            if self.sidecar_notice:
                self.sidecar_notice("Subtitles unavailable: " + ", ".join(missing) + ". Video download continues.")
        return [(path, target) for path, target in (result or []) if Path(path).is_file()]
