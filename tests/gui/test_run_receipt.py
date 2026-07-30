from llm_youtube_comment_generation.interfaces.gui.run_receipt import (
    comment_receipt,
    reply_receipt,
)


def test_comment_receipt_explains_evidence_and_output():
    text = comment_receipt({
        "video_title": "A useful video",
        "counts": {"comments": 120, "replies": 45},
        "transcript": {
            "source": "youtube-captions",
            "language": "en",
        },
        "api_operations_used": 9,
        "packet_characters": 33147,
    }, "D:/runs/video")

    assert "A useful video" in text
    assert "120 comments" in text
    assert "youtube-captions (en)" in text
    assert "33,147 packet characters" in text
    assert "9 logical YouTube API operations" in text
    assert "D:/runs/video" in text


def test_reply_receipt_explains_queue_and_transcript():
    text = reply_receipt({
        "video": {"title": "Reply video"},
        "total": 20,
        "waiting": 6,
        "transcript": {"source": "saved-transcript", "language": "en"},
    })

    assert "Reply video" in text
    assert "20 people found" in text
    assert "6 waiting" in text
    assert "saved-transcript (en)" in text


def test_receipt_exposes_the_actual_reason_a_transcript_was_missing():
    text = comment_receipt({
        "video_title": "No transcript",
        "transcript": {
            "availability": "fetch_failed",
            "source": "youtube-transcript-api",
            "detail": (
                "the transcript library is not installed, so no caption "
                "track could be looked up (ModuleNotFoundError)"
            ),
        },
    })

    assert "Transcript note:" in text
    assert "ModuleNotFoundError" in text
