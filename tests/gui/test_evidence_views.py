from llm_youtube_comment_generation.interfaces.gui.evidence_views import (
    comments_text,
    description_text,
    metadata_text,
    replies_text,
)


def test_video_elements_render_as_separate_copyable_text():
    video = {
        "video_id": "gC-J7zwYMAM",
        "title": "A title",
        "channel_title": "A channel",
        "description": "A useful description.",
        "view_count": 1234,
    }

    assert "Title: A title" in metadata_text(video)
    assert "https://www.youtube.com/watch?v=gC-J7zwYMAM" in metadata_text(video)
    assert description_text(video) == "A useful description."


def test_comments_and_replies_keep_ids_and_parent_relationships():
    comments = comments_text([{
        "comment_id": "parent-1",
        "author": "@viewer",
        "like_count": 12,
        "total_reply_count": 3,
        "text": "The comment.",
    }])
    replies = replies_text([{
        "comment_id": "reply-1",
        "parent_comment_id": "parent-1",
        "author": "@other",
        "text": "The reply.",
    }])

    assert "ID: parent-1" in comments
    assert "12 likes, 3 replies" in comments
    assert "Parent comment ID: parent-1" in replies
    assert "The reply." in replies
