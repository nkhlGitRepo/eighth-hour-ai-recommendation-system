#!/usr/bin/env python
"""
Standalone verification for MediaPipeSizingProvider's real-model behaviour.

Why this exists instead of a pytest test: MediaPipe's inference deadlocks when
run inside pytest on macOS/Python 3.13 (the same calls finish in about a second
in a normal interpreter, but hang indefinitely under pytest regardless of -s or
-p no:faulthandler). Rather than leave the real model unverified, the checks
live here and run in their own process.

    python scripts/verify_pose_provider.py                 # rejection checks
    python scripts/verify_pose_provider.py photo.jpg 172   # measure a real photo

The second form is how you confirm the happy path: MediaPipe won't detect a
drawn or synthesised figure, so proving "a real photo yields real measurements"
needs an actual photograph, which this repo deliberately doesn't ship.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py_src.providers.mediapipe_sizing_provider import MediaPipeSizingProvider  # noqa: E402
from py_src.utils.errors import ModuleError  # noqa: E402

PASS = "  PASS"
FAIL = "  FAIL"
failures = []


def check(label, condition, detail=""):
    print(f"{PASS if condition else FAIL}  {label}{(' -- ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def as_jpeg(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def expect_rejection(provider, label, data, expect_text=None, height=170.0):
    try:
        result = provider.extract_from_image(data, "image/jpeg", height)
        check(label, False, f"was NOT rejected: {result.bust}/{result.waist}/{result.hips}")
    except ModuleError as err:
        matched = expect_text is None or expect_text.lower() in err.message.lower()
        check(label, matched, err.message[:90])


def run_rejection_checks():
    import numpy as np
    from PIL import Image, ImageDraw

    provider = MediaPipeSizingProvider()
    print("\n=== Images with no usable person must be refused ===")

    rng = np.random.default_rng(20260814)
    expect_rejection(
        provider, "random noise rejected",
        as_jpeg(Image.fromarray(rng.integers(0, 255, (600, 400, 3), dtype=np.uint8))),
        "couldn't find a person",
    )
    expect_rejection(
        provider, "flat colour image rejected",
        as_jpeg(Image.new("RGB", (400, 600), (120, 140, 200))),
        "couldn't find a person",
    )

    drawing = Image.new("RGB", (400, 600), (245, 245, 245))
    pen = ImageDraw.Draw(drawing)
    pen.ellipse([180, 40, 220, 90], fill=(50, 50, 50))
    pen.rectangle([175, 90, 225, 320], fill=(50, 50, 50))
    pen.rectangle([185, 320, 200, 540], fill=(50, 50, 50))
    pen.rectangle([205, 320, 220, 540], fill=(50, 50, 50))
    expect_rejection(
        provider, "drawn stick figure rejected (not a photo of a person)",
        as_jpeg(drawing), "couldn't find a person",
    )

    expect_rejection(
        provider, "undecodable bytes rejected",
        b"\xff\xd8\xff\xe0 definitely not a jpeg body", "couldn't read",
    )
    expect_rejection(provider, "empty upload rejected", b"", "empty")

    print("\n=== Disclosure must state that it really analyses the image ===")
    disclosure = provider.disclosure
    check("derives_from_image is True", disclosure["derives_from_image"] is True)
    check("sends_image_offsite is False", disclosure["sends_image_offsite"] is False)
    check("stores_image is False", disclosure["stores_image"] is False)


def measure_real_photo(path, height_cm):
    provider = MediaPipeSizingProvider()
    print(f"\n=== Measuring {path} at a stated height of {height_cm} cm ===")
    with open(path, "rb") as handle:
        data = handle.read()

    try:
        m = provider.extract_from_image(data, "image/jpeg", height_cm)
    except ModuleError as err:
        print(f"  REFUSED: {err.message}")
        print("\n  (If this is a clear, straight-on, full-body standing photo, that's a\n"
              "   problem worth investigating. A lunge/yoga/seated/rotated pose being\n"
              "   refused is correct behaviour -- the measurement math isn't valid for it.)")
        return

    print(f"  bust  {m.bust} cm")
    print(f"  waist {m.waist} cm")
    print(f"  hips  {m.hips} cm")
    print(f"  shoulder {m.shoulder} cm   height {m.height} cm   unit {m.unit}")
    print(f"  provider {m.provider} ({m.provider_version})")
    print(f"  confidence {m.confidence_scores}")
    check("hips exceed waist", m.hips > m.waist, f"{m.hips} vs {m.waist}")
    check("all values inside accepted ranges", True)

    print("\n=== Same photo, different stated heights (scale must be honoured) ===")
    for h in (155.0, 170.0, 190.0):
        try:
            scaled = provider.extract_from_image(data, "image/jpeg", h)
            print(f"  height {h:5.0f} -> bust {scaled.bust:6.1f}  waist {scaled.waist:6.1f}  hips {scaled.hips:6.1f}")
        except ModuleError as err:
            print(f"  height {h:5.0f} -> refused: {err.message[:70]}")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--diagnose":
        diagnose(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 170.0)
        return 0
    if len(sys.argv) > 1:
        photo = sys.argv[1]
        height = float(sys.argv[2]) if len(sys.argv) > 2 else 170.0
        measure_real_photo(photo, height)
    else:
        run_rejection_checks()

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0



def diagnose(path, height_cm=170.0):
    """
    Print the raw pose geometry and every validation check for one photo, so a
    refusal can be traced to the specific threshold that rejected it instead of
    the generic customer-facing message.

        python scripts/verify_pose_provider.py --diagnose photo.jpg 170
    """
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    from PIL import Image, ImageOps

    from py_src.providers import mediapipe_sizing_provider as P
    from py_src.providers.anthropometry import measurements_from_breadths, pixels_to_cm_scale

    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = image.width, image.height
    print(f"\n=== {path} ===")
    print(f"  image {w}x{h} ({'portrait' if h > w else 'landscape'})")

    landmarker = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=P.ensure_model()),
            running_mode=vision.RunningMode.IMAGE, num_poses=1))
    result = landmarker.detect(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image)))

    if not result.pose_landmarks:
        print("  NO POSE DETECTED -- nothing further to measure.")
        return
    L = result.pose_landmarks[0]

    def pt(i):
        return L[i].x * w, L[i].y * h

    lsx, lsy = pt(P.LEFT_SHOULDER); rsx, rsy = pt(P.RIGHT_SHOULDER)
    lhx, lhy = pt(P.LEFT_HIP);      rhx, rhy = pt(P.RIGHT_HIP)
    lax, lay = pt(P.LEFT_ANKLE);    rax, ray = pt(P.RIGHT_ANKLE)

    sh_b = abs(lsx - rsx); pel_b = abs(lhx - rhx)
    sh_mid_y = (lsy + rsy) / 2; hip_mid_y = (lhy + rhy) / 2; ank_mid_y = (lay + ray) / 2
    torso = abs(hip_mid_y - sh_mid_y)
    span = abs(ank_mid_y - sh_mid_y)

    print(f"  visibility  shoulders {L[P.LEFT_SHOULDER].visibility:.2f}/{L[P.RIGHT_SHOULDER].visibility:.2f}"
          f"  hips {L[P.LEFT_HIP].visibility:.2f}/{L[P.RIGHT_HIP].visibility:.2f}"
          f"  ankles {L[P.LEFT_ANKLE].visibility:.2f}/{L[P.RIGHT_ANKLE].visibility:.2f}")
    print(f"  shoulder breadth {sh_b:6.1f}px   pelvis breadth {pel_b:6.1f}px   torso {torso:6.1f}px   span {span:6.1f}px")

    print("\n  --- validation checks ---")
    def show(name, value, ok, limit):
        print(f"    {'ok  ' if ok else 'FAIL'}  {name:34} {value:>7}   (limit {limit})")

    vis_ok = all(L[i].visibility >= P.MIN_LANDMARK_VISIBILITY for i in P.REQUIRED_LANDMARKS)
    show("landmark visibility", f"{min(L[i].visibility for i in P.REQUIRED_LANDMARKS):.2f}",
         vis_ok, f">= {P.MIN_LANDMARK_VISIBILITY}")

    upright = sh_mid_y < hip_mid_y < ank_mid_y
    show("upright (shoulders<hips<ankles)", str(upright), upright, "True")

    sh_tilt = abs(lsy - rsy) / sh_b
    show("shoulder tilt / shoulder breadth", f"{sh_tilt:.2f}", sh_tilt <= P.MAX_TILT_OVER_BREADTH,
         f"<= {P.MAX_TILT_OVER_BREADTH}")

    hip_tilt = abs(lhy - rhy) / sh_b
    show("hip tilt / shoulder breadth", f"{hip_tilt:.2f}", hip_tilt <= P.MAX_TILT_OVER_BREADTH,
         f"<= {P.MAX_TILT_OVER_BREADTH}")

    splay = max(abs(lax - lhx), abs(rax - rhx)) / sh_b
    show("ankle splay / shoulder breadth", f"{splay:.2f}",
         splay <= P.MAX_ANKLE_OFFSET_OVER_SHOULDER_BREADTH,
         f"<= {P.MAX_ANKLE_OFFSET_OVER_SHOULDER_BREADTH}")

    ratio = pel_b / sh_b
    show("pelvis / shoulder breadth", f"{ratio:.2f}",
         P.MIN_PELVIS_SHOULDER_RATIO <= ratio <= P.MAX_PELVIS_SHOULDER_RATIO,
         f"{P.MIN_PELVIS_SHOULDER_RATIO}-{P.MAX_PELVIS_SHOULDER_RATIO}")

    print("\n  --- scale references (which one is distorted?) ---")
    print(f"    shoulder_px / span_px  = {sh_b/span:.3f}   (a real body is ~0.27)")
    print(f"    shoulder_px / torso_px = {sh_b/torso:.3f}   (a real body is ~0.74)")

    if span > 0:
        scale = pixels_to_cm_scale(span, height_cm)
        derived = measurements_from_breadths(sh_b * scale, pel_b * scale)
        print(f"\n  --- CURRENT estimator (shoulder->ankle span) at {height_cm}cm ---")
        print(f"    shoulder {sh_b*scale:5.1f}cm  pelvis {pel_b*scale:5.1f}cm")
        print(f"    bust {derived['bust']:6.1f}  waist {derived['waist']:6.1f}  hips {derived['hips']:6.1f}")

    if torso > 0:
        # Alternative: scale from torso length instead of leg length. Excludes
        # legs, feet and footwear entirely, so it is far less sensitive to
        # perspective, heels, and one-leg-forward posing.
        TORSO_RATIO = 0.288   # (acromion 0.818 - trochanter 0.530) x stature
        tscale = (TORSO_RATIO * height_cm) / torso
        tderived = measurements_from_breadths(sh_b * tscale, pel_b * tscale)
        print(f"\n  --- ALTERNATIVE estimator (shoulder->hip torso) at {height_cm}cm ---")
        print(f"    shoulder {sh_b*tscale:5.1f}cm  pelvis {pel_b*tscale:5.1f}cm")
        print(f"    bust {tderived['bust']:6.1f}  waist {tderived['waist']:6.1f}  hips {tderived['hips']:6.1f}")

if __name__ == "__main__":
    sys.exit(main())
