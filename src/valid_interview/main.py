from fractions import Fraction
from math import isclose
from tempfile import NamedTemporaryFile
from typing import Literal

import vpdq  # type: ignore
from fastapi import FastAPI, HTTPException, UploadFile
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pydantic import BaseModel, PlainSerializer
from shortuuid import ShortUUID
from typing_extensions import Annotated

BUCKET_TOLERANCE = 0.01
QUALITY_THRESHOLD = 50
DISTANCE_TOLERANCE = 108
CANNONICAL_ASPECT_RATIOS = {
    Fraction(16, 9),
    Fraction(1, 1),
    Fraction(4, 5),
    Fraction(9, 16),
}

AspectRatio = Annotated[
    Fraction,
    PlainSerializer(lambda f: f"{f.numerator}:{f.denominator}", return_type=str),
]


class VideoEntry(BaseModel):
    video_id: str
    width: int
    height: int
    aspect_ratio: AspectRatio
    ratio_bucket: AspectRatio | Literal["Other"]
    filename: str


class MatchEntry(BaseModel):
    video_id: str
    filename: str
    confidence: float


temp_file_to_video_entry: dict[str, VideoEntry] = {}

app = FastAPI(title="Valid Interview", version="0.1.0")


@app.post("/upload")
async def post_upload(files: list[UploadFile]) -> list[VideoEntry]:
    new_entries: dict[str, VideoEntry] = {}
    for file in files:
        with NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(await file.read())
            temp_file.flush()
            metadata = extractMetadata(createParser(temp_file.name))
            aspect_ratio = Fraction(metadata.get("width"), metadata.get("height"))
            ratio_bucket: AspectRatio | Literal["Other"] = "Other"
            for canonical_aspect_ratio in CANNONICAL_ASPECT_RATIOS:
                if isclose(
                    aspect_ratio, canonical_aspect_ratio, rel_tol=BUCKET_TOLERANCE
                ):
                    aspect_ratio = canonical_aspect_ratio
                    ratio_bucket = aspect_ratio
                    break
            new_entries[temp_file.name] = VideoEntry(
                video_id=ShortUUID(alphabet="0123456789").random(length=8),
                width=metadata.get("width"),
                height=metadata.get("height"),
                aspect_ratio=aspect_ratio,
                ratio_bucket=ratio_bucket,
                filename=file.filename,
            )
    temp_file_to_video_entry.update(new_entries)
    return new_entries.values()


@app.get("/match")
async def get_match(video_id: str) -> list[MatchEntry]:
    query_temp_filename, query_video_entry = next(
        (
            (query_temp_filename, entry)
            for query_temp_filename, entry in temp_file_to_video_entry.items()
            if entry.video_id == video_id
        ),
        (None, None),
    )
    if query_video_entry is None:
        raise HTTPException(status_code=404)

    query_frames = [
        frame
        for frame in vpdq.computeHash(query_temp_filename)
        if frame.quality >= QUALITY_THRESHOLD
    ]

    match_entries: list[MatchEntry] = []
    for (
        target_temp_filename,
        target_video_entry,
    ) in temp_file_to_video_entry.items():
        if (
            target_video_entry.ratio_bucket == query_video_entry.ratio_bucket
            or target_video_entry.ratio_bucket == "Other"
        ):
            continue

        target_frames = [
            frame
            for frame in vpdq.computeHash(target_temp_filename)
            if frame.quality >= QUALITY_THRESHOLD
        ]

        shorter_frames, longer_frames = (
            (query_frames, target_frames)
            if len(query_frames) <= len(target_frames)
            else (target_frames, query_frames)
        )

        if len(shorter_frames) == 0:
            continue

        matched = 0
        for shorter_frame in shorter_frames:
            for longer_frame in longer_frames:
                if (
                    bin(int(shorter_frame.hex, 16) ^ int(longer_frame.hex, 16)).count(
                        "1"
                    )
                    <= DISTANCE_TOLERANCE
                ):
                    matched += 1
                    break
        match_entries.append(
            MatchEntry(
                video_id=target_video_entry.video_id,
                filename=target_video_entry.filename,
                confidence=round(matched / len(shorter_frames), 2),
            )
        )
    match_entries.sort(key=lambda entry: entry.confidence, reverse=True)
    return match_entries


@app.get("/videos")
async def get_videos(ratio: str | None = None) -> list[VideoEntry]:
    if ratio is None:
        return temp_file_to_video_entry.values()
    if ratio not in {
        f"{r.numerator}:{r.denominator}" for r in CANNONICAL_ASPECT_RATIOS
    }:
        raise HTTPException(status_code=400)
    return [
        entry
        for entry in temp_file_to_video_entry.values()
        if entry.ratio_bucket
        == Fraction(int(ratio.split(":")[0]), int(ratio.split(":")[1]))
    ]


@app.delete("/videos/{video_id}")
async def delete_video(video_id: str) -> None:
    query_temp_filename, query_video_entry = next(
        (
            (query_temp_filename, entry)
            for query_temp_filename, entry in temp_file_to_video_entry.items()
            if entry.video_id == video_id
        ),
        (None, None),
    )
    if query_video_entry is None:
        raise HTTPException(status_code=404)
    temp_file_to_video_entry.pop(query_temp_filename)
    return {"deleted": video_id}
