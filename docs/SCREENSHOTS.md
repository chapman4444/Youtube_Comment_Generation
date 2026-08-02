# Screenshots

The application working through one comment, from an empty window to a
manually published post.

These images live here rather than in `README.md` on purpose. The review
archive stages source, tests, tools and the architecture notes, but not
`docs/screenshots/`, so a gallery embedded in the README arrived as broken
image links in the one document a reviewer reads first. Moving it here keeps
`README.md` free of local image references, which lets the archived README
stay byte-identical to the checkout without shipping several megabytes of
PNGs that show real commenters' names and words.

![The application ready for a video](screenshots/start-screen.png)

| Source video | Retrieved public discussion |
| --- | --- |
| ![The source video in a browser](screenshots/youtube-video.png) | ![Retrieved YouTube comments](screenshots/comments.png) |

| Generated writing packet | Answer validation |
| --- | --- |
| ![Generated comment packet](screenshots/generated-packet.png) | ![Returned answer being validated](screenshots/answer-validation.png) |

![The manually published final comment](screenshots/published-comment.png)

## The complete workflow

| Retrieval activity | Video metadata |
| --- | --- |
| ![Retrieval activity and run receipt](screenshots/activity-log.png) | ![Retrieved video metadata](screenshots/video-metadata.png) |

| Video description | Transcript and manual source controls |
| --- | --- |
| ![Retrieved video description](screenshots/video-description.png) | ![Transcript with manual source controls](screenshots/transcript-sources.png) |

| Retrieved replies | Full generated-packet view |
| --- | --- |
| ![Retrieved YouTube replies](screenshots/replies.png) | ![Full generated packet](screenshots/generated-packet-detail.png) |

| Model-answer review | Model critique and hardened final |
| --- | --- |
| ![Packet and model answer side by side](screenshots/model-answer-review.png) | ![Model critique and hardened final](screenshots/model-critique.png) |
