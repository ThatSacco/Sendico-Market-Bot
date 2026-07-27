from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass, replace
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageOps

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadedImage:
    image_index: int
    url: str
    mime_type: str
    data: bytes


@dataclass(slots=True)
class CardCrop:
    crop_index: int
    source_image_index: int
    mime_type: str
    data: bytes
    perceptual_hash: int = 0
    quality_score: float = 0.0


@dataclass(slots=True)
class _Candidate:
    source_image_index: int
    data: bytes
    perceptual_hash: int
    quality_score: float
    sort_key: tuple[int, int]


class LocalCardExtractor:
    """Detect and crop card-shaped regions without using vision-model tokens.

    The extractor combines contour-based rectangle detection with an axis-aligned
    line-grid fallback. It anchors physical quantities to the listing photo that
    contains the most cards, then uses perceptual hashes to replace those crops
    with sharper close-ups from alternate photos without double-counting them.
    """

    def __init__(
        self,
        *,
        max_crops: int = 40,
        analysis_max_dimension_px: int = 2200,
        crop_max_dimension_px: int = 1400,
        jpeg_quality: int = 86,
        minimum_card_area_ratio: float = 0.012,
        maximum_card_area_ratio: float = 0.98,
        minimum_rectangularity: float = 0.58,
        card_aspect_ratio_min: float = 0.52,
        card_aspect_ratio_max: float = 0.84,
        duplicate_phash_distance: int = 10,
        crop_padding_percent: float = 0.025,
    ) -> None:
        self.max_crops = max(1, max_crops)
        self.analysis_max_dimension_px = max(700, analysis_max_dimension_px)
        self.crop_max_dimension_px = max(500, crop_max_dimension_px)
        self.jpeg_quality = max(55, min(95, jpeg_quality))
        self.minimum_card_area_ratio = max(0.001, minimum_card_area_ratio)
        self.maximum_card_area_ratio = max(
            self.minimum_card_area_ratio,
            min(1.0, maximum_card_area_ratio),
        )
        self.minimum_rectangularity = max(0.25, min(0.98, minimum_rectangularity))
        self.card_aspect_ratio_min = max(0.35, card_aspect_ratio_min)
        self.card_aspect_ratio_max = min(0.95, card_aspect_ratio_max)
        self.duplicate_phash_distance = max(0, duplicate_phash_distance)
        self.crop_padding_percent = max(0.0, min(0.12, crop_padding_percent))

    def extract(self, images: list[DownloadedImage]) -> list[CardCrop]:
        """Return one crop slot per physical card visible in one anchor photo.

        Quantity is fixed by the legitimate listing photo containing the largest
        number of card-shaped regions. Alternate photos may replace an anchor
        crop with a sharper perceptually matching view, but an unmatched front,
        back, close-up or slab photo can never create another physical-card slot.
        """
        candidates_by_image: dict[int, list[_Candidate]] = {}
        for downloaded in images:
            try:
                candidates = self._extract_from_image(downloaded)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Local card detection failed for listing image %s: %s",
                    downloaded.image_index,
                    exc,
                )
                candidates = []
            candidates_by_image[downloaded.image_index] = candidates
            LOGGER.info(
                "Local preprocessing found %d card-shaped region(s) in image %d",
                len(candidates),
                downloaded.image_index,
            )

        nonempty = {
            image_index: items
            for image_index, items in candidates_by_image.items()
            if items
        }
        if not nonempty:
            return []

        # The image with the most simultaneous cards defines physical quantity.
        # Ties prefer the earliest listing photo, which is normally the seller's
        # overview/front image rather than a later back or detail photo.
        anchor_index = min(
            nonempty,
            key=lambda index: (-len(nonempty[index]), index),
        )

        groups: list[_Candidate] = list(nonempty[anchor_index])
        source_order = sorted(index for index in nonempty if index != anchor_index)

        replacements = 0
        matched_alternates = 0
        ignored_unmatched = 0
        for image_index in source_order:
            matched_group_indexes: set[int] = set()
            for candidate in sorted(
                nonempty[image_index],
                key=lambda item: item.quality_score,
                reverse=True,
            ):
                best_group: int | None = None
                best_distance = self.duplicate_phash_distance + 1
                for group_index, existing in enumerate(groups):
                    if group_index in matched_group_indexes:
                        continue
                    distance = _hamming_distance(
                        candidate.perceptual_hash,
                        existing.perceptual_hash,
                    )
                    if distance < best_distance:
                        best_distance = distance
                        best_group = group_index

                if (
                    best_group is not None
                    and best_distance <= self.duplicate_phash_distance
                ):
                    matched_group_indexes.add(best_group)
                    matched_alternates += 1
                    if candidate.quality_score > groups[best_group].quality_score:
                        groups[best_group] = replace(
                            candidate,
                            # Preserve the anchor image as quantity evidence even
                            # when a sharper alternate photo supplies the pixels.
                            source_image_index=groups[best_group].source_image_index,
                            sort_key=groups[best_group].sort_key,
                        )
                        replacements += 1
                    continue

                # Do not append unmatched alternate views. This is the critical
                # quantity guard for front/back/close-up photos of one card.
                ignored_unmatched += 1

        groups = groups[: self.max_crops]
        crops = [
            CardCrop(
                crop_index=index,
                source_image_index=item.source_image_index,
                mime_type="image/jpeg",
                data=item.data,
                perceptual_hash=item.perceptual_hash,
                quality_score=item.quality_score,
            )
            for index, item in enumerate(groups, start=1)
        ]
        LOGGER.info(
            "Local preprocessing anchored quantity to image %d with %d physical "
            "card slot(s); matched %d alternate view(s), used %d sharper "
            "replacement(s), ignored %d unmatched alternate crop(s)",
            anchor_index,
            len(crops),
            matched_alternates,
            replacements,
            ignored_unmatched,
        )
        return crops

    def _extract_from_image(self, downloaded: DownloadedImage) -> list[_Candidate]:
        image = _decode_rgb(downloaded.data)
        image = _resize_longest(image, self.analysis_max_dimension_px)
        bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

        quads = self._detect_contour_quads(bgr)
        if len(quads) < 2:
            line_quads = self._detect_axis_aligned_grid_quads(bgr)
            quads = _dedupe_quads([*quads, *line_quads])

        if not quads and self._looks_like_single_card(bgr):
            height, width = bgr.shape[:2]
            quads = [
                np.array(
                    [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                    dtype=np.float32,
                )
            ]

        candidates: list[_Candidate] = []
        for quad in quads:
            warped = self._warp_card(bgr, quad)
            if warped is None:
                continue
            data = self._encode_crop(warped)
            perceptual_hash = _perceptual_hash(warped)
            quality = _quality_score(warped)
            x, y, _, _ = cv2.boundingRect(quad.astype(np.int32))
            candidates.append(
                _Candidate(
                    source_image_index=downloaded.image_index,
                    data=data,
                    perceptual_hash=perceptual_hash,
                    quality_score=quality,
                    sort_key=(y, x),
                )
            )

        candidates.sort(key=lambda item: item.sort_key)
        return candidates

    def _detect_contour_quads(self, bgr: np.ndarray) -> list[np.ndarray]:
        height, width = bgr.shape[:2]
        image_area = float(width * height)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        masks: list[np.ndarray] = []
        for low, high in ((35, 110), (60, 180)):
            edges = cv2.Canny(gray, low, high)
            edges = cv2.morphologyEx(
                edges,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
                iterations=2,
            )
            masks.append(edges)

        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            41,
            7,
        )
        adaptive = cv2.morphologyEx(
            adaptive,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
            iterations=1,
        )
        masks.append(adaptive)

        quads: list[np.ndarray] = []
        for mask in masks:
            contours, _ = cv2.findContours(
                mask,
                cv2.RETR_LIST,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            for contour in contours:
                contour_area = abs(cv2.contourArea(contour))
                area_ratio = contour_area / image_area
                if not (
                    self.minimum_card_area_ratio
                    <= area_ratio
                    <= self.maximum_card_area_ratio
                ):
                    continue

                rect = cv2.minAreaRect(contour)
                rect_width, rect_height = rect[1]
                if min(rect_width, rect_height) < 110:
                    continue
                rect_area = rect_width * rect_height
                if rect_area <= 0:
                    continue
                rectangularity = contour_area / rect_area
                if rectangularity < self.minimum_rectangularity:
                    continue

                aspect = min(rect_width, rect_height) / max(rect_width, rect_height)
                if not (
                    self.card_aspect_ratio_min
                    <= aspect
                    <= self.card_aspect_ratio_max
                ):
                    continue

                perimeter = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    quad = approx.reshape(4, 2).astype(np.float32)
                else:
                    quad = cv2.boxPoints(rect).astype(np.float32)
                quads.append(quad)

        return _dedupe_quads(quads)

    def _detect_axis_aligned_grid_quads(self, bgr: np.ndarray) -> list[np.ndarray]:
        """Find aligned card grids from long vertical and horizontal border lines."""
        height, width = bgr.shape[:2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 45, 145)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=max(45, min(width, height) // 12),
            minLineLength=max(100, min(width, height) // 4),
            maxLineGap=max(12, min(width, height) // 40),
        )
        if lines is None:
            return []

        vertical: list[int] = []
        horizontal: list[int] = []
        for raw in lines[:, 0, :]:
            x1, y1, x2, y2 = [int(value) for value in raw]
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            if dy >= max(1, dx * 4):
                vertical.append(round((x1 + x2) / 2))
            elif dx >= max(1, dy * 4):
                horizontal.append(round((y1 + y2) / 2))

        vertical = _cluster_positions(vertical, tolerance=max(8, width // 120))
        horizontal = _cluster_positions(horizontal, tolerance=max(8, height // 120))
        if len(vertical) < 2 or len(horizontal) < 2:
            return []

        quads: list[np.ndarray] = []
        image_area = float(width * height)
        # Consecutive clustered lines are used as cell boundaries. This avoids
        # treating two neighbouring cards together as one landscape rectangle.
        for x1, x2 in zip(vertical, vertical[1:]):
            card_width = x2 - x1
            if card_width < 110 or card_width > width * 0.75:
                continue
            for y1, y2 in zip(horizontal, horizontal[1:]):
                card_height = y2 - y1
                if card_height < 150 or card_height > height * 0.98:
                    continue
                aspect = min(card_width, card_height) / max(
                    card_width,
                    card_height,
                )
                if not (
                    self.card_aspect_ratio_min
                    <= aspect
                    <= self.card_aspect_ratio_max
                ):
                    continue
                area_ratio = (card_width * card_height) / image_area
                if not (
                    self.minimum_card_area_ratio
                    <= area_ratio
                    <= self.maximum_card_area_ratio
                ):
                    continue
                if not _box_has_border_support(edges, x1, y1, x2, y2):
                    continue
                quads.append(
                    np.array(
                        [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                        dtype=np.float32,
                    )
                )
        return _dedupe_quads(quads)

    def _looks_like_single_card(self, bgr: np.ndarray) -> bool:
        height, width = bgr.shape[:2]
        if min(width, height) < 300:
            return False
        aspect = min(width, height) / max(width, height)
        return self.card_aspect_ratio_min <= aspect <= self.card_aspect_ratio_max

    def _warp_card(self, bgr: np.ndarray, quad: np.ndarray) -> np.ndarray | None:
        ordered = _order_quad(quad)
        center = ordered.mean(axis=0)
        ordered = center + (ordered - center) * (1.0 + self.crop_padding_percent)
        height, width = bgr.shape[:2]
        ordered[:, 0] = np.clip(ordered[:, 0], 0, width - 1)
        ordered[:, 1] = np.clip(ordered[:, 1], 0, height - 1)

        top_left, top_right, bottom_right, bottom_left = ordered
        target_width = int(
            max(
                np.linalg.norm(bottom_right - bottom_left),
                np.linalg.norm(top_right - top_left),
            )
        )
        target_height = int(
            max(
                np.linalg.norm(top_right - bottom_right),
                np.linalg.norm(top_left - bottom_left),
            )
        )
        if min(target_width, target_height) < 100:
            return None

        destination = np.array(
            [
                [0, 0],
                [target_width - 1, 0],
                [target_width - 1, target_height - 1],
                [0, target_height - 1],
            ],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(ordered, destination)
        warped = cv2.warpPerspective(bgr, matrix, (target_width, target_height))
        if warped.shape[1] > warped.shape[0]:
            warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
        return _resize_bgr_longest(warped, self.crop_max_dimension_px)

    def _encode_crop(self, bgr: np.ndarray) -> bytes:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        output = io.BytesIO()
        Image.fromarray(rgb).save(
            output,
            format="JPEG",
            quality=self.jpeg_quality,
            optimize=True,
        )
        return output.getvalue()


def _decode_rgb(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        source = ImageOps.exif_transpose(source)
        return source.convert("RGB").copy()


def _resize_longest(image: Image.Image, maximum: int) -> Image.Image:
    longest = max(image.size)
    if longest <= maximum:
        return image
    scale = maximum / longest
    return image.resize(
        (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )


def _resize_bgr_longest(image: np.ndarray, maximum: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(width, height)
    if longest <= maximum:
        return image
    scale = maximum / longest
    return cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _quad_box(quad: np.ndarray) -> tuple[int, int, int, int]:
    x, y, width, height = cv2.boundingRect(quad.astype(np.int32))
    return x, y, x + width, y + height


def _overlap_over_smaller(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    smaller = min(first_area, second_area)
    return intersection / smaller if smaller else 0.0


def _dedupe_quads(quads: Iterable[np.ndarray]) -> list[np.ndarray]:
    ranked = sorted(
        (np.asarray(quad, dtype=np.float32).reshape(4, 2) for quad in quads),
        key=lambda quad: abs(cv2.contourArea(quad)),
        reverse=True,
    )
    kept: list[np.ndarray] = []
    for quad in ranked:
        box = _quad_box(quad)
        if any(_overlap_over_smaller(box, _quad_box(existing)) >= 0.78 for existing in kept):
            continue
        kept.append(quad)
    kept.sort(key=lambda quad: (_quad_box(quad)[1], _quad_box(quad)[0]))
    return kept


def _cluster_positions(values: list[int], tolerance: int) -> list[int]:
    if not values:
        return []
    values = sorted(values)
    clusters: list[list[int]] = [[values[0]]]
    for value in values[1:]:
        if value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [round(sum(cluster) / len(cluster)) for cluster in clusters]


def _box_has_border_support(
    edges: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> bool:
    height, width = edges.shape[:2]
    radius = max(2, min(width, height) // 350)

    def vertical_density(x: int) -> float:
        left = max(0, x - radius)
        right = min(width, x + radius + 1)
        strip = edges[max(0, y1):min(height, y2), left:right]
        return float(np.count_nonzero(strip)) / max(1, strip.size)

    def horizontal_density(y: int) -> float:
        top = max(0, y - radius)
        bottom = min(height, y + radius + 1)
        strip = edges[top:bottom, max(0, x1):min(width, x2)]
        return float(np.count_nonzero(strip)) / max(1, strip.size)

    supports = [
        vertical_density(x1),
        vertical_density(x2),
        horizontal_density(y1),
        horizontal_density(y2),
    ]
    return sum(value >= 0.035 for value in supports) >= 3


def _perceptual_hash(bgr: np.ndarray) -> int:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(np.float32(resized))[:8, :8]
    flattened = coefficients.flatten()
    median = float(np.median(flattened[1:]))
    value = 0
    for bit in flattened > median:
        value = (value << 1) | int(bool(bit))
    return value


def _quality_score(bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    area = float(gray.shape[0] * gray.shape[1])
    return math.log1p(sharpness) * math.log1p(area)


def _hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()
