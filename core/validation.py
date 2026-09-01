"""Scene-level validation: how well does the simulated product correspond to
the real Earth reference it was derived from.

This is deliberately NOT a pixel-difference comparison. The simulated image
has been through blur, motion smear, noise, atmosphere and tone mapping, so a
pixel-wise diff against the pristine reference would always show "different"
without saying anything about whether the simulation is behaving sensibly.
Comparing at the scene/feature level -- does the same footprint validate, is
land cover distributed the same way, is the frame itself usable -- answers
the question the brief actually asks, without presenting a diff score as if
it meant something it does not.

Every metric here says what it is and how it was computed. The final
confidence figure is explicitly labelled as a simulated indicator, not a
measured scientific result -- it is a disclosed weighted combination of the
checks above it, not an independent measurement.
"""

import numpy as np

from core.classify import classify_scene


def _classification_similarity(reference_classification, simulated_classification):
    """0-100 similarity between two class-fraction distributions (L1-based).

    Both classifications come from the same spectral-index classifier
    (core.classify.classify_scene) applied to two different inputs -- the
    real reference reflectance and the simulated DN rescaled to the same
    footing -- so this compares like with like using the one classifier this
    project already audits and trusts, rather than a new model.
    """
    if not reference_classification.get("available") or not simulated_classification.get("available"):
        return {
            "available": False,
            "reason": "classification unavailable for reference and/or simulated scene",
        }

    ref_frac = reference_classification["classFractionsPercent"]
    sim_frac = simulated_classification["classFractionsPercent"]
    classes = sorted(set(ref_frac) | set(sim_frac))
    l1 = sum(abs(ref_frac.get(c, 0.0) - sim_frac.get(c, 0.0)) for c in classes)
    # L1 distance over class-fraction percentages ranges 0 (identical) to 200
    # (fully disjoint); halving and inverting gives a 0-100 similarity.
    similarity = max(0.0, 100.0 - l1 / 2.0)

    return {
        "available": True,
        "similarityPercent": round(similarity, 1),
        "referenceFractionsPercent": ref_frac,
        "simulatedFractionsPercent": sim_frac,
        "method": "100 - (sum of |reference% - simulated%| per class) / 2, "
                  "both classified by core.classify.classify_scene",
    }


def compare_scenes(reference_reflectance, reference_classification, dn, sensor_report,
                    coordinate_validation, quality, validation, band_names):
    """Assemble the Geospatial Validation panel's metrics.

    `reference_classification` is the classification already computed on the
    real reflectance elsewhere in generate_product -- passed in rather than
    recomputed, so it can never disagree with what the product's own
    "classification" field says. `quality`/`validation` are likewise the
    existing assess_quality/validate_product results, reused, not redone.
    """
    bit_depth = int(sensor_report.get("bitDepth", 12))
    max_dn = float((2 ** bit_depth) - 1)
    simulated_reflectance_proxy = np.clip(dn.astype("float32") / max_dn, 0.0, None)
    simulated_classification = classify_scene(simulated_reflectance_proxy, band_names)

    land_cover = _classification_similarity(reference_classification, simulated_classification)

    footprint_alignment = {
        "aligned": True,
        "method": (
            "The simulated product and the Earth reference are both rendered from "
            "the identical windowed read (same bbox, same output raster shape) -- "
            "alignment is guaranteed by construction, not independently measured. "
            "There is no registration step to validate because there was never a "
            "second, separately-fetched image to misalign."
        ),
    }

    quality_realism = {
        "qualityScore": (quality or {}).get("score"),
        "qualityGrade": (quality or {}).get("grade"),
        "productStatus": (validation or {}).get("status"),
        "productStatusLabel": (validation or {}).get("label"),
        "method": "Pass-through of core.quality.assess_quality / validate_product, "
                  "not recomputed here.",
    }

    checks = {
        "coordinatesValidated": bool((coordinate_validation or {}).get("valid")),
        "footprintCalculated": True,
        "sensorModelApplied": True,
        "referenceSceneMatched": bool(reference_reflectance is not None),
    }

    # Disclosed weighted mean, itemised the same way assess_quality already
    # is -- never a black box, and explicitly not presented as measured.
    factors = {
        "coordinateValidity": 100.0 if checks["coordinatesValidated"] else 0.0,
        "footprintAlignment": 100.0 if footprint_alignment["aligned"] else 0.0,
        "landCoverSimilarity": land_cover.get("similarityPercent", 0.0) if land_cover.get("available") else 50.0,
        "imageQualityRealism": quality_realism["qualityScore"] or 0.0,
    }
    weights = {"coordinateValidity": 0.2, "footprintAlignment": 0.2,
               "landCoverSimilarity": 0.3, "imageQualityRealism": 0.3}
    confidence = sum(factors[k] * weights[k] for k in factors)

    return {
        "checklist": checks,
        "coordinateValidation": coordinate_validation,
        "footprintAlignment": footprint_alignment,
        "landCoverSimilarity": land_cover,
        "imageQualityRealism": quality_realism,
        "overallConfidence": {
            "score": round(confidence, 1),
            "factors": {k: round(v, 1) for k, v in factors.items()},
            "weights": weights,
            "label": (
                "SIMULATED confidence indicator -- a disclosed weighted combination "
                "of the checks above, not a measured scientific result and not a "
                "statement about ASC_074's real-world imaging performance."
            ),
        },
    }
