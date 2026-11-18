# Instagram Profile & Engagement Scraper

Get **public Instagram profile stats and post engagement**, with no login and no Instagram account. Paste usernames or profile links and get one row per profile: followers, following, posts, bio, links in bio and verified badge, plus the **likes and comments of its newest posts**, **average likes and comments**, **engagement rate** and **posting frequency**. You can also paste single post and reel links.

**You only pay for rows that are delivered.** Profiles that don't exist, are private or restricted, or could not be loaded come back as error rows that cost nothing.

## What can this Instagram scraper do?

- 👤 Get a profile's **username, name, bio, links in bio, verified badge and profile picture**
- 👥 Get **exact follower and following counts** (`104,325,949`, not `104M`) and the post count
- 📈 Get the **engagement rate**: (average likes + average comments) / followers × 100, over the newest posts
- ❤️ Get **average likes, average comments, posting frequency per week** and the **date of the last post**
- 🖼️ Get **one row per recent post**: type (photo, carousel, reel, video), date, caption, hashtags, mentions, likes, comments, image and video links, location, collab flag
- 🔗 Scrape **any post or reel link**, including posts older than the newest 12
- 🆓 **Failed inputs are free**: not found, private, age-restricted and blocked inputs return a free error row with the reason
- 📦 Export to **JSON, CSV, Excel, XML or HTML**, or pull the data through the Apify API

## Why use this scraper?

- **No account, no risk to yours.** It reads only what Instagram shows to a visitor who is not logged in. It never logs in and never uses cookies from an account.
- **Engagement figures ready to use.** Engagement rate, average likes and comments and posting frequency come calculated in the profile row, so you can sort influencers or competitors straight away.
- **Fair billing.** You pay one `profile` event per profile row and one `post` event per post row. Error rows are free. A profile or post given twice is scraped and charged once.
- **Every column, every time.** Every row has the same keys, with `null` for missing values, so CSV and Excel exports always line up.

## How to scrape Instagram profiles

1. Click **Try for free**.
2. Paste one or more **Instagram profiles**: usernames, @handles or profile links.
3. Keep **Include recent posts** on to get likes, comments and the engagement rate (turn it off for profile stats only).
4. Optionally paste **post and reel links**.
5. Click **Start** and download your data when the run finishes.

## Input

| Field | Description |
|---|---|
| **Instagram profiles** | Usernames (`nasa`), @handles (`@nasa`) or profile links (`https://www.instagram.com/nasa/`). Duplicates are removed. |
| **Include recent posts** | On by default. Opens each of the newest posts on the profile (up to 12) and returns its likes and comments. The profile's engagement figures are calculated from them. |
| **Recent posts per profile** | How many of the newest posts to open per profile, 0 to 12. Default 12. |
| **Post and reel links** | Single posts to scrape: `/p/...`, `/reel/...` or `/tv/...` links. |
| **Max concurrency** | How many profiles or posts load at the same time, each through its own proxy IP. Default 3. Instagram limits each IP, so keep it low. |
| **Proxy configuration** | Apify Proxy (datacenter) by default. Switch to the **RESIDENTIAL** group if many rows come back as `loginRequired` or `blocked`. |

Example input:

```json
{
    "usernames": ["nasa", "@nike", "https://www.instagram.com/natgeo/"],
    "includeRecentPosts": true,
    "maxPostsPerProfile": 12,
    "postUrls": ["https://www.instagram.com/p/DfahZrMjAqq/"],
    "maxConcurrency": 3,
    "proxyConfiguration": { "useApifyProxy": true }
}
```

## Output example

A profile row (`recordType: "profile"`), with all post columns `null`:

```json
{
    "recordType": "profile",
    "inputUrl": "nasa",
    "url": "https://www.instagram.com/nasa/",
    "username": "nasa",
    "fullName": "NASA",
    "userId": "528817151",
    "biography": "Making the seemingly impossible, possible. ✨",
    "externalUrl": "https://www.nasa.gov",
    "externalUrls": [
        { "title": "NASA.gov Homepage", "url": "https://www.nasa.gov" },
        { "title": "Become a NASA Astronaut", "url": "https://go.nasa.gov/astro2026" }
    ],
    "isVerified": true,
    "isPrivate": false,
    "followersCount": 104325949,
    "followingCount": 91,
    "postsCount": 5014,
    "profilePicUrl": "https://scontent-sea5-1.cdninstagram.com/v/t51.2885-19/29090066_...",
    "recentPostsAnalysed": 12,
    "avgLikes": 203541.2,
    "avgComments": 946.6,
    "postingFrequencyPerWeek": 6.71,
    "lastPostAt": "2026-11-18T01:00:50+00:00",
    "recentPostUrls": ["https://www.instagram.com/p/Dfc1mYxFevS/", "https://www.instagram.com/p/DfahZrMjAqq/"],
    "engagementRatePct": 0.196,
    "shortcode": null,
    "...": "all post columns null",
    "scrapedAt": "2026-11-18T02:05:01+00:00",
    "error": null,
    "errorMessage": null
}
```

A post row (`recordType: "post"`), with all profile columns `null`:

```json
{
    "recordType": "post",
    "inputUrl": "nasa",
    "url": "https://www.instagram.com/p/DfahZrMjAqq/",
    "engagementRatePct": 0.2477,
    "shortcode": "DfahZrMjAqq",
    "mediaId": "4024676116912147114",
    "type": "photo",
    "takenAt": "2026-11-06T21:00:08+00:00",
    "caption": "Galaxy in bloom\n\nData from our Hubble, Chandra, and Spitzer telescopes blend to reveal a starburst galaxy ... #NASA #Galaxy #Flower",
    "hashtags": ["NASA", "Galaxy", "Flower"],
    "mentions": [],
    "likeCount": 257538,
    "commentCount": 873,
    "displayUrl": "https://scontent-sea5-1.cdninstagram.com/v/t51.82787-15/886800608_...",
    "imageUrls": ["https://scontent-sea5-1.cdninstagram.com/v/t51.82787-15/886800608_..."],
    "videoUrl": null,
    "carouselMediaCount": null,
    "ownerUsername": "nasa",
    "ownerId": "528817151",
    "isCollab": false,
    "locationName": null,
    "scrapedAt": "2026-11-18T02:04:22+00:00",
    "error": null,
    "errorMessage": null
}
```

An input that could not be scraped gives a free error row with the same keys, all `null` except these:

```json
{
    "recordType": "profile",
    "inputUrl": "dataji_no_such_user",
    "url": "https://www.instagram.com/dataji_no_such_user/",
    "scrapedAt": "2026-11-18T02:04:15+00:00",
    "error": "notFound",
    "errorMessage": "Instagram says this page isn't available. The username does not exist, was changed, or the account was removed."
}
```

## Output fields

Common to all rows:

| Field | Description |
|---|---|
| `recordType` | `profile` or `post` (error rows keep the type of what was asked for) |
| `inputUrl` | What you entered, unchanged. Posts found on a profile carry the profile you entered |
| `url` | Link to the profile or post |
| `engagementRatePct` | Profile: (average likes + average comments) / followers × 100 over the posts analysed. Post: (likes + comments) / the profile's followers × 100 (only for posts found on a profile). `null` when likes are hidden |
| `scrapedAt` | When the row was made (UTC) |
| `error`, `errorMessage` | `null` for delivered rows. For failed inputs: the error code and the reason (see FAQ) |

Profile rows:

| Field | Description |
|---|---|
| `username`, `fullName`, `userId` | Username, display name and numeric account id |
| `biography` | Bio text |
| `externalUrl`, `externalUrls` | First link in bio, and all of them with their titles: `[{"title": "...", "url": "..."}]` |
| `isVerified`, `isPrivate` | Verified badge; private account |
| `followersCount`, `followingCount` | Exact follower and following counts |
| `postsCount` | Number of posts. Instagram shows logged-out visitors a rounded number above 9,999 (`32K` → `32000`) |
| `profilePicUrl` | Profile picture link (150 × 150) |
| `recentPostsAnalysed` | How many recent posts were opened and used for the figures below |
| `avgLikes`, `avgComments` | Average likes and comments over those posts |
| `postingFrequencyPerWeek` | Posts per week between the oldest and newest of those posts, leaving out pinned posts |
| `lastPostAt` | Date of the newest of those posts |
| `recentPostUrls` | Links of the posts shown on the profile (up to 12, pinned posts first) |

Post rows:

| Field | Description |
|---|---|
| `shortcode`, `mediaId` | The code in the post link and the numeric media id |
| `type` | `photo`, `carousel`, `reel` or `video` |
| `takenAt` | When the post was published (UTC) |
| `caption`, `hashtags`, `mentions` | Caption text, and the #hashtags and @mentions in it |
| `likeCount` | Likes (`null` when the owner hid the like count) |
| `commentCount` | Number of comments |
| `displayUrl`, `imageUrls` | Main image, and all images (one per carousel item) |
| `videoUrl` | Video file link for reels and videos |
| `carouselMediaCount` | Number of items in a carousel |
| `ownerUsername`, `ownerId` | The account that published the post |
| `isCollab` | `true` for a collab post with co-authors |
| `locationName` | The tagged location, when there is one |

The **Profiles**, **Posts** and **Errors** tabs in the run's **Output** show the most useful columns.

## Pricing

This actor uses **pay per event** pricing. Pricing: set at publish.

| Event | When it is charged | Price |
|---|---|---|
| `profile` | Once for each profile row delivered to the dataset | $X.XX per 1,000 profiles |
| `post` | Once for each post row delivered to the dataset | $X.XX per 1,000 posts |

A profile with its 12 recent posts is 1 `profile` event and 12 `post` events. Turn **Include recent posts** off to pay for profile rows only. Error rows (not found, private, restricted, login required, blocked, invalid input) are **never charged**. Proxy costs are included. The run stops cleanly when it reaches the spending limit you set, and the status message tells you what was left.

## Limits

Instagram shows less to visitors who are not logged in, and this actor never logs in:

- **Only the 12 newest posts per profile** (pinned posts included) are visible. For older posts, paste their links into **Post and reel links**.
- **No comments.** Only the number of comments. Comment text needs a login.
- **No view or play counts** for reels and videos, no follower lists, no stories, no highlights content.
- **No business category, contact email or phone**: Instagram doesn't show them to logged-out visitors.
- **The post count is rounded** by Instagram above 9,999 (`32K`). Follower and following counts are exact.
- **Image and video links expire** after a few days (Instagram signs them). Download the files soon if you need them.
- **Private accounts**: only the profile details (followers, following, posts, bio) are public; you get them in a free `privateProfile` row, without posts.
- **Age-restricted accounts** (alcohol brands and similar) are hidden from logged-out visitors: free `restricted` row with the public counts.
- Instagram limits how much each IP may load. The actor paces requests and changes proxy IP on a block, but large runs may see some `blocked` or `loginRequired` rows; they are free, and you can run them again later.

## Use cases

- **Influencer vetting**: compare engagement rates, average likes and posting frequency before a campaign
- **Competitor and brand monitoring**: track followers and engagement of a list of accounts over time
- **Content research**: see which post types (reels, carousels, photos) get the most likes and comments
- **Campaign reporting**: likes and comments of specific posts and reels from their links
- **Lead lists**: links in bio of creators and brands in a niche

## FAQ

### Do I need an Instagram account?
No. The actor only reads what Instagram shows to a visitor who is not logged in. It never logs in, never uses cookies from an account, and never tries to get around login walls.

### How is the engagement rate calculated?
(average likes + average comments) / followers × 100, over the recent posts the actor opened (up to 12, including pinned posts). For example NASA on 2026-11-18: 203,541 average likes + 947 average comments with 104,325,949 followers gives `0.196` (%). Accounts with hidden like counts have no engagement rate.

### Which inputs fail, and why?
Each failed input gets one free error row with an `error` code:

| Code | Meaning |
|---|---|
| `notFound` | Instagram says the profile or post isn't available: it does not exist, was deleted, or the username changed. |
| `privateProfile` | The account is private. The row still has its public details (followers, following, posts, bio). |
| `restricted` | Instagram hides the profile or post from logged-out visitors, for example age-restricted brands ("You must be 21 years old or over"). Profile rows keep the public counts. |
| `loginRequired` | Instagram asked to log in, twice, on two different proxy IPs. Usually temporary throttling: try again later or with residential proxies. |
| `blocked` | Instagram did not return the page after 3 tries on 3 different proxy IPs. Try again later or with residential proxies. |
| `invalidInput` | Not an Instagram username, profile link or post link: for example a story, explore or share link. |
| `failed` | An unexpected problem while reading the page. Please report it in the **Issues** tab. |

If one of a profile's recent posts fails, you get a free post error row for it and the profile figures use the other posts.

### Why do some profiles show fewer than 12 posts analysed?
The profile has fewer posts, some posts failed (free error rows), you set **Recent posts per profile** lower, or the run reached your spending limit.

### Why does a post appear with another account as owner?
It is a collab post: the profile you asked for is a co-author, so Instagram shows it on that profile's grid too. `isCollab` is `true`.

### Can I get comments?
No. Instagram shows comments only to logged-in users, and this actor never logs in. You get the comment count of every post.

### Can I use it through the API?
Yes. You can start runs and download results with the [Apify API](https://docs.apify.com/api/v2), the Apify JavaScript and Python clients, or integrations like Make, Zapier and Google Sheets.

## Is it legal to scrape Instagram?

This actor only collects information that accounts publish on their public Instagram profiles and posts, as shown to any visitor who is not logged in. It does not log in and does not collect comments or follower lists. Still, please use the data responsibly:

- **Personal data.** Profiles of creators and individuals are personal data under the **GDPR** (EU and UK), the **CCPA** (California) and similar laws. You need a lawful basis, such as legitimate interest, to store and use them, keep only what you need, and honour people's rights, including the right to object and to have data deleted.
- **Outreach.** If you contact people with the data, follow the rules for marketing messages, such as **CAN-SPAM** in the US and the GDPR and ePrivacy rules in Europe.
- **Instagram's terms.** Instagram's terms restrict automated collection. You are responsible for how you use this actor and the data.

You can read more in Apify's blog post on [the legality of web scraping](https://blog.apify.com/is-web-scraping-legal/), and check with a lawyer if you are unsure.

**Removal requests.** If your information appears in output from this actor and you want it removed, or have a privacy question, email **privacy@dataji.io**. We aim to answer within 30 days.

## Need something custom?

This actor is one of many data tools we build at Dataji. If you need something different, we can build it for you, whether that's a change to this actor or a scraper for any other website or data source.

Popular requests include:

- scheduled runs that track followers and engagement of a list of accounts over time
- dashboards and reports built on the data
- delivery straight to Google Sheets, your CRM or a webhook
- extra fields, filters or checks

These are only examples. If the data is online, we can most likely collect it for you. Tell us what you're trying to build through the [contact form](https://dataji.io/contact-us/) or email support@dataji.io. For bugs or questions about this actor, please use the **Issues** tab.

## Support

Found a bug or need a field that is missing? Open an issue in the **Issues** tab and we'll take a look.
