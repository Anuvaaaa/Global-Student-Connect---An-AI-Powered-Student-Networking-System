from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from engagement.models import Notification, UserEngagement
from engagement.utils import record_mission_progress
from matching.utils import is_blocked_either_way

from .forms import CommentForm, PostForm
from .models import Comment, Like, Post

POSTS_PER_PAGE = 10
FEED_WINDOW_DAYS = 7  # prototype only ever shows the last 7 days of moments

# Confirmed against the real Mission.key values in Django admin.
# Of the 5 seeded missions, only 'like_3_posts' is something this app
# can observe — 'join_a_group', 'send_20_messages', 'start_conversation',
# and 'use_translation_5x' belong to matching/chat and get wired up
# there, not here.
LIKE_MISSION_KEY = 'like_3_posts'
COMMENT_MISSION_KEY = None  # no comment-specific mission exists yet


def _notification_link_for_post(post):
    """
    Builds a link to `post` on the feed. Deliberately does NOT compute
    a page number here — an earlier version did, but that number was
    calculated once, at the moment the like/comment happened, and
    baked permanently into the notification. Since the feed is live
    and keeps growing, any posts added between then and whenever the
    notification is actually clicked push the target further back,
    making that baked-in page number stale — which is exactly what
    caused "View" to land on a plain feed with nothing found.

    Instead this just passes the post's ID via ?highlight=, and
    feed_view recomputes its real, CURRENT position fresh on every
    request — always correct, no matter how much time (or how many
    new posts) passed in between.
    """
    cutoff = timezone.now() - timedelta(days=FEED_WINDOW_DAYS)

    if post.created_at < cutoff:
        # Post has aged out of the 7-day feed window entirely — no
        # page will ever contain it, so just link to the plain feed.
        return reverse('social:home')

    return f"{reverse('social:home')}?highlight={post.id}#card-{post.id}"


def _visible_posts_queryset(user):
    """
    Posts from the last FEED_WINDOW_DAYS days only, most recent first,
    minus posts from anyone blocked in either direction. is_blocked_
    either_way() is a stub right now (always False, see matching/utils.py)
    — once Person C's real Block cascade lands this starts filtering
    with zero changes needed here.
    """
    cutoff = timezone.now() - timedelta(days=FEED_WINDOW_DAYS)

    qs = (
        Post.objects
        .filter(created_at__gte=cutoff)
        .select_related('user', 'user__profile', 'user__university')
        .annotate(
            like_count=Count('likes', filter=Q(likes__active=True), distinct=True),
            comment_count=Count('comments', distinct=True),
        )
        .order_by('-created_at')
    )

    if user.is_authenticated:
        blocked_user_ids = {
            post.user_id for post in qs.only('id', 'user_id')
            if is_blocked_either_way(user, post.user)
        }
        if blocked_user_ids:
            qs = qs.exclude(user_id__in=blocked_user_ids)

    return qs


def _day_label(post_date, today, yesterday):
    if post_date == today:
        return 'Today'
    if post_date == yesterday:
        return 'Yesterday'
    # Cross-platform safe (no %-d, which isn't reliable on Windows)
    return f"{post_date.strftime('%B')} {post_date.day}"


def _group_posts_by_day(posts):
    """
    Groups an already-ordered (newest first) iterable of posts into
    (label, [posts]) tuples — replaces the frontend's JS-driven
    Today/Yesterday/date divider logic.
    """
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    groups = []
    current_label = None
    current_bucket = []

    for post in posts:
        post_date = timezone.localtime(post.created_at).date()
        label = _day_label(post_date, today, yesterday)

        if label != current_label:
            if current_bucket:
                groups.append((current_label, current_bucket))
            current_label = label
            current_bucket = [post]
        else:
            current_bucket.append(post)

    if current_bucket:
        groups.append((current_label, current_bucket))

    return groups


@login_required
def feed_view(request):
    posts_qs = _visible_posts_queryset(request.user)

    try:
        page_number = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page_number = 1
    page_number = max(page_number, 1)

    try:
        open_comments_post_id = int(request.GET.get('open_comments', 0)) or None
    except (TypeError, ValueError):
        open_comments_post_id = None

    try:
        highlight_post_id = int(request.GET.get('highlight', 0)) or None
    except (TypeError, ValueError):
        highlight_post_id = None

    # Cumulative reveal, not true pagination: "See older posts" re-requests
    # the page with a bigger limit, so everything already shown stays
    # visible and older posts get appended below — matching what people
    # actually expect from a "load more" button, rather than swapping the
    # whole feed out for a different slice each click.
    limit = page_number * POSTS_PER_PAGE

    if highlight_post_id:
        # Arriving from a notification's "View" link. That link can't
        # know in advance which page the target post falls on — without
        # this, a post older than the default 10 simply wouldn't be on
        # the page at all, so there'd be nothing to scroll to or
        # highlight. Count how many visible posts sit at-or-above it in
        # feed order and expand the limit to guarantee it's included.
        target_qs = posts_qs.filter(id=highlight_post_id)
        target_created_at = target_qs.values_list('created_at', flat=True).first()
        if target_created_at is not None:
            position = posts_qs.filter(created_at__gte=target_created_at).count()
            if position > limit:
                limit = position
                # Keep page_number in sync with the actual expanded
                # limit, so 'current_page'/'next_page_number' below (and
                # the hidden next_page fields on every action form)
                # reflect what's really on screen — otherwise the next
                # "See older posts" click would ask for FEWER posts than
                # are already showing and the feed would shrink.
                page_number = -(-limit // POSTS_PER_PAGE)  # ceiling division

    # Fetch one extra row to know whether there's still more beyond this
    # limit, without running a separate COUNT() query.
    posts_list = list(posts_qs[:limit + 1])
    has_next = len(posts_list) > limit
    posts_list = posts_list[:limit]

    post_ids = [post.id for post in posts_list]

    liked_post_ids = set(
        Like.objects
        .filter(user=request.user, post_id__in=post_ids, active=True)
        .values_list('post_id', flat=True)
    )

    # Attach each post's visible (non-blocked) comments, oldest first,
    # matching the prototype's comment thread order.
    for post in posts_list:
        comments = post.comments.select_related('user').order_by('created_at')
        post.visible_comments = [
            c for c in comments if not is_blocked_either_way(request.user, c.user)
        ]

    context = {
        'active_page': 'home',
        'day_groups': _group_posts_by_day(posts_list),
        'has_next': has_next,
        'current_page': page_number,
        'next_page_number': page_number + 1,
        'liked_post_ids': liked_post_ids,
        'open_comments_post_id': open_comments_post_id,
        'post_form': PostForm(),
        'comment_form': CommentForm(),
    }
    return render(request, 'social/home.html', context)


@login_required
def create_post_view(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.user = request.user
            post.save()
        # On invalid input we just fall through to the redirect — the
        # 200-char limit is also enforced client-side via maxlength, so a
        # server-side rejection here should only happen on a malformed
        # request, not a normal user mistake.
    return _redirect_to_feed(request)


def _redirect_to_feed(request, open_comments_post_id=None):
    """
    Redirects back to the feed, preserving whichever page the user had
    loaded via "See older posts" — every like/comment/delete form
    includes a hidden 'next_page' field carrying this value. No #card-
    anchor here; exact scroll position is restored client-side via
    sessionStorage in home.html's JS instead, since anchor scrolling
    snaps the target to the top of the viewport rather than preserving
    where it actually was on screen.

    open_comments_post_id: if given, the redirect also tells feed_view
    to render that post's comment section already expanded — without
    this, adding/deleting a comment reloads the page with every comment
    section collapsed again, hiding the comment you just wrote.
    """
    next_page = request.POST.get('next_page', '1')
    url = f"{reverse('social:home')}?page={next_page}"
    if open_comments_post_id:
        url += f"&open_comments={open_comments_post_id}"
    return redirect(url)


@login_required
def toggle_like_view(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if request.method == 'POST':
        like, created = Like.objects.get_or_create(user=request.user, post=post)
        engagement, _ = UserEngagement.objects.get_or_create(user=request.user)

        if created:
            # This user has NEVER liked this post before — full credit:
            # engagement counter, mission progress, notification. This
            # only fires once per (user, post) pair, ever, no matter how
            # many times it's toggled afterward.
            engagement.likes_given += 1
            engagement.save(update_fields=['likes_given'])

            is_own_post = (post.user_id == request.user.id)

            # Mission credit is meant to reward engaging with OTHER
            # people's content — liking your own post to farm progress
            # is the same category of exploit as the toggle bug, just a
            # different angle on it.
            if LIKE_MISSION_KEY and not is_own_post:
                record_mission_progress(request.user, LIKE_MISSION_KEY)

            if not is_own_post:
                Notification.objects.create(
                    user=post.user,
                    type='message',
                    title='New like on your moment',
                    description=f'{request.user.get_full_name() or request.user.username} liked your post.',
                    cta_label='View',
                    cta_href=_notification_link_for_post(post),
                )
        elif like.active:
            # Currently liked -> this click is an unlike. No mission/
            # notification reversal — those were one-time credit for
            # ever having liked it, not a live count.
            like.active = False
            like.save(update_fields=['active'])
            engagement.likes_given = max(0, engagement.likes_given - 1)
            engagement.save(update_fields=['likes_given'])
        else:
            # Previously unliked, re-liking now. Engagement counter goes
            # back up (it reflects current state), but no repeat mission
            # credit or notification — they already got that the first
            # time they ever liked this post.
            like.active = True
            like.save(update_fields=['active'])
            engagement.likes_given += 1
            engagement.save(update_fields=['likes_given'])

    return _redirect_to_feed(request)


@login_required
def add_comment_view(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.user = request.user
            comment.post = post
            comment.save()

            engagement, _ = UserEngagement.objects.get_or_create(user=request.user)
            engagement.comments_made += 1
            engagement.save(update_fields=['comments_made'])

            is_own_post = (post.user_id == request.user.id)

            if COMMENT_MISSION_KEY and not is_own_post:
                record_mission_progress(request.user, COMMENT_MISSION_KEY)

            if not is_own_post:
                Notification.objects.create(
                    user=post.user,
                    type='message',
                    title='New comment on your moment',
                    description=f'{request.user.get_full_name() or request.user.username} commented on your post.',
                    cta_label='View',
                    cta_href=_notification_link_for_post(post),
                )

    return _redirect_to_feed(request, open_comments_post_id=post.id)


@login_required
def delete_comment_view(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    post_id = comment.post_id

    # Only the comment's own author can delete it. Letting post owners
    # delete others' comments too would be a moderation feature — that
    # belongs in the moderation app's scope, not here.
    if request.method == 'POST' and comment.user_id == request.user.id:
        comment.delete()

    return _redirect_to_feed(request, open_comments_post_id=post_id)


@login_required
def delete_post_view(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Only the post's own author can delete it. This also cascades to
    # the post's Comment and Like rows automatically via on_delete=CASCADE
    # on those models' post FK — no extra cleanup needed here.
    if request.method == 'POST' and post.user_id == request.user.id:
        post.delete()

    return _redirect_to_feed(request)
