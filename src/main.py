from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from core.input_handler import InputHandler
from core.vision import TemplateMatchResult, TemplateMatcher


def _parse_region(region: str | None) -> dict[str, int] | None:
    if not region:
        return None
    parts = [int(part) for part in region.split(",")]
    if len(parts) != 4:
        raise ValueError("Region must be x,y,width,height")
    x, y, w, h = parts
    return {"left": x, "top": y, "width": w, "height": h}


def print_matches(matches: Iterable[TemplateMatchResult]) -> None:
    for match in matches:
        cx, cy = match.center
        print(
            f"[{match.template_name}] score={match.confidence:.3f} "
            f"scale={match.scale:.2f} center=({cx},{cy})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Template matching demo for DirectX-friendly RPA")
    parser.add_argument("--templates", type=Path, default=Path("templates"), help="Directory containing PNG templates")
    parser.add_argument("--threshold", type=float, default=0.82, help="Match threshold")
    parser.add_argument("--region", type=str, default=None, help="Capture region as x,y,width,height")
    parser.add_argument("--click-first", action="store_true", help="Move and click the best match center")
    args = parser.parse_args()

    matcher = TemplateMatcher(template_dir=args.templates, threshold=args.threshold, capture_region=_parse_region(args.region))
    input_handler = InputHandler()

    matches = matcher.locate()
    print_matches(matches)

    if args.click_first:
        best = matcher.locate_best()
        if best:
            x, y = best.center
            input_handler.click(x, y)


if __name__ == "__main__":
    main()
