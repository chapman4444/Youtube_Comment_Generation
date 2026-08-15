"""A seven-response thread fixture, synthetic but structurally real.

Captured from a live scan and then pseudonymised: every display name,
channel and comment id here is invented, and the video is SYNTHETIC01.
What is preserved is the shape the regression needs - three direct
responses and four nested, two authors who each posted twice, one
run-together mention, and one mention prefixed with the invisible
U+200B that YouTube inserts before a rendered mention.

Channel ids are stored as stems and expanded below. A literal
channel-id-shaped string may not appear in a committed file, which is
why the rest of the suite writes them the same way.
"""


def _channel(stem: str) -> str:
    return ("UC" + stem.ljust(22, "x"))[:24]


LEGO_THREAD = {
    "owner_channel_id": "threadowner",
    "video": {
        "video_id": "SYNTHETIC01",
        "title": "SYNTHETIC EXAMPLE"
    },
    "comment": {
        "comment_id": "Thread01",
        "author": "@threadowner",
        "author_channel_id": "threadowner",
        "text": "Apparently BAM has invented franchise debt collection with a bonus feature: when a franchisee owes corporate money, property sitting in the store becomes part of the recovery even when corporate knows some of it was consigned. Great system if you are corporate. The consignor gets promoted to involuntary collateral for a debt they never incurred. Internal franchise rules do not make third-party own",
        "like_count": 44,
        "published_at": "2026-08-13T08:09:18Z"
    },
    "replies": [
        {
            "comment_id": "Thread01.Response01",
            "author": "@normagraham3",
            "author_channel_id": "normagraham3",
            "text": "I was a victim of a company, that rented property, and refused to exit a lease after the lease was over, it's only because the company did it to a thousand people, that we were able to sue.  I had to pay thousands to \"wi",
            "like_count": 7,
            "published_at": "2026-08-13T09:54:25Z"
        },
        {
            "comment_id": "Thread01.Response02",
            "author": "@knightsquire",
            "author_channel_id": "knightsquire",
            "text": "@normagraham3omg I know a company doing that now.  No matter how many times you tell them you are terminating after the contract expires, they keep treating you as though you are a customer and helping themselves to you",
            "like_count": 6,
            "published_at": "2026-08-13T10:47:20Z"
        },
        {
            "comment_id": "Thread01.Response03",
            "author": "@flychomper",
            "author_channel_id": "flychomper",
            "text": "\u200b@normagraham3 - actually, you did \"sign\" by entering into an agreement.  You don't need a piece of paper to have a contract.\n\nWhat the piece of paper does is to specify the terms of the agreement so in case of disputes",
            "like_count": 1,
            "published_at": "2026-08-13T13:03:51Z"
        },
        {
            "comment_id": "Thread01.Response04",
            "author": "@sixthwilbury",
            "author_channel_id": "sixthwilbury",
            "text": "\"The consignor gets promoted to involuntary collateral for a debt they never incurred.\" Great read. That's pretty crazy, and should (hopefully) prevent anyone else from entering into such an agreement until Ammon McNeff ",
            "like_count": 0,
            "published_at": "2026-08-13T18:18:20Z"
        },
        {
            "comment_id": "Thread01.Response05",
            "author": "@sixthwilbury",
            "author_channel_id": "sixthwilbury",
            "text": "@flychomper Seconded. One of those things that many people don't realize: an oral agreement is still a contract, assuming it has all of the required elements (offer, consideration, purpose is legal, etc). Having it in",
            "like_count": 0,
            "published_at": "2026-08-13T18:35:44Z"
        },
        {
            "comment_id": "Thread01.Response06",
            "author": "@nazerine",
            "author_channel_id": "nazerine",
            "text": "Its even more elaborate than this, they seem to be the ones creating the debt that is owed by telling stores its okay to be late on payment or not taking over leases when they said they would etc. \n\nSo promote being a fr",
            "like_count": 1,
            "published_at": "2026-08-13T19:22:04Z"
        },
        {
            "comment_id": "Thread01.Response07",
            "author": "@nazerine",
            "author_channel_id": "nazerine",
            "text": "@flychomper but wouldn\u2019t that mean just telling them you\u2019re terminating or exiting the agreement hold the same weight as verbally entering one?",
            "like_count": 0,
            "published_at": "2026-08-13T19:23:58Z"
        }
    ]
}

LEGO_THREAD["owner_channel_id"] = _channel(
    LEGO_THREAD["owner_channel_id"])
LEGO_THREAD["comment"]["author_channel_id"] = _channel(
    LEGO_THREAD["comment"]["author_channel_id"])
for _reply in LEGO_THREAD["replies"]:
    _reply["author_channel_id"] = _channel(_reply["author_channel_id"])
