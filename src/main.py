from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from core.fsm import ActionState, ErrorState, IdleState, SearchingState, StateContext, StateMachine
from core.input_handler import InputHandler
from core.ocr_engine import OCREngine
from core.vision import TemplateMatchResult, TemplateMatcher
from utils.notifier import Notifier


def _parse_region(region: str | None) -> tuple[int, int, int, int] | None:
    if not region:
        return None
    parts = [int(part) for part in region.split(",")]
    if len(parts) != 4:
        raise ValueError("Region must be x,y,width,height")
    x, y, w, h = parts
    return x, y, w, h


def _parse_region_dict(region: str | None) -> dict[str, int] | None:
    parsed = _parse_region(region)
    if parsed is None:
        return None
    x, y, w, h = parsed
    return {"left": x, "top": y, "width": w, "height": h}


def print_matches(matches: Iterable[TemplateMatchResult]) -> None:
    for match in matches:
        cx, cy = match.center
        print(
            f"[{match.template_name}] score={match.confidence:.3f} "
            f"scale={match.scale:.2f} center=({cx},{cy})"
        )


def load_webhook_config(path: Path = Path("config.json"), profiles_dir: Path = Path("profiles")) -> str:
    active_profile = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        active_profile = data.get("active_profile")
        if data.get("webhook_url"):
            return data["webhook_url"]

    profile_candidates = []
    if active_profile:
        profile_candidates.append(profiles_dir / f"{active_profile}.json")
    profile_candidates.append(profiles_dir / "default.json")

    for profile_path in profile_candidates:
        if not profile_path.exists():
            continue
        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if profile_data.get("webhook_url"):
            return profile_data["webhook_url"]
    return ""


def run_ocr(region: tuple[int, int, int, int], numeric: bool = False) -> None:
    engine = OCREngine()
    if numeric:
        value = engine.read_number(region)
        print(f"Numeric OCR result: {value}")
    else:
        text = engine.read_text(region)
        print(f"Text OCR result: {text}")


def run_state_machine(matcher: TemplateMatcher, handler: InputHandler, notifier: Notifier) -> None:
    states = {
        "idle": IdleState(),
        "search": SearchingState(),
        "action": ActionState(),
        "error": ErrorState(),
    }

    def logger(message: str) -> None:
        print(message)

    context = StateContext(matcher=matcher, controller=handler, notifier=notifier, logger=logger)
    machine = StateMachine(initial_state="idle", states=states, sleep_interval=0.1)
    machine.run(context)


def main() -> None:
    parser = argparse.ArgumentParser(description="DirectX-friendly RPA entrypoint with FSM and OCR support")
    parser.add_argument("--templates", type=Path, default=Path("templates"), help="Directory containing PNG templates")
    parser.add_argument("--threshold", type=float, default=0.82, help="Match threshold")
    parser.add_argument("--region", type=str, default=None, help="Capture region as x,y,width,height")
    parser.add_argument("--click-first", action="store_true", help="Move and click the best match center")
    parser.add_argument("--ocr-region", type=str, help="OCR region as x,y,w,h")
    parser.add_argument("--ocr-number", action="store_true", help="Parse OCR output as number")
    args = parser.parse_args()

    if args.ocr_region:
        run_ocr(_parse_region(args.ocr_region), numeric=args.ocr_number)
        return

    matcher = TemplateMatcher(
        template_dir=args.templates, threshold=args.threshold, capture_region=_parse_region_dict(args.region)
    )
    input_handler = InputHandler()
    notifier = Notifier(load_webhook_config())

    if args.click_first:
        best = matcher.locate_best()
        if best:
            x, y = best.center
            input_handler.click(x, y)
        return

    run_state_machine(matcher, input_handler, notifier)


if __name__ == "__main__":
    main()
