import urllib.parse

import requests
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from engagement.utils import get_badge_progress, get_mission_progress
from matching.utils import cleanup_matching_state_for_deleted_user
from social.models import Interest, UserInterest

from .forms import ProfileSetupForm
from .models import Profile, User
from .utils import get_block_message
from .verification import complete_verification, get_verification_block_message

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def login_view(request):
    """
    Landing / sign-in page. Google OAuth (google_login_view /
    google_callback_view below) is the only real sign-in path — the old
    dev username/password form was a temporary placeholder used before
    Google sign-in was wired up and has been removed. block_message can
    still arrive here via a redirect from google_callback_view (e.g. a
    banned/suspended account, or a non-academic email).
    """
    if request.user.is_authenticated:
        return redirect('social:home')

    return render(request, 'accounts/index.html', {
        'block_message': request.session.pop('login_block_message', None),
    })


def google_login_view(request):
    """
    Step 1 of the redirect-based flow: sends the browser to Google's own
    consent screen via a full page redirect (not a JS/iframe widget) —
    this sidesteps the FedCM/third-party-storage issues that break the
    "Sign in with Google" JS button on plain http:// origins in current
    Chrome. google_callback_view below handles the return trip.
    """
    redirect_uri = request.build_absolute_uri(reverse('accounts:google_callback'))
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
    }
    return redirect(f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}")


def google_callback_view(request):
    """
    Step 2: Google redirects here with either ?code=... (success) or
    ?error=... (user cancelled, or e.g. not an approved test user).
    Exchanges the code for an ID token server-to-server, verifies it,
    then runs the exact same block/verification logic that used to live
    in the dev login view so a banned/suspended/non-academic-domain
    user can't get through.
    """
    error = request.GET.get('error')
    if error:
        request.session['login_block_message'] = "Google sign-in was cancelled or denied."
        return redirect('accounts:login')

    code = request.GET.get('code')
    if not code:
        return redirect('accounts:login')

    redirect_uri = request.build_absolute_uri(reverse('accounts:google_callback'))
    token_response = requests.post(GOOGLE_TOKEN_ENDPOINT, data={
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        'code': code,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    })

    if token_response.status_code != 200:
        request.session['login_block_message'] = "Couldn't complete Google sign-in. Please try again."
        return redirect('accounts:login')

    token = token_response.json().get('id_token')

    try:
        payload = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID
        )
    except ValueError:
        request.session['login_block_message'] = "Invalid Google credential."
        return redirect('accounts:login')

    email = payload.get('email')
    google_sub = payload.get('sub')

    # Google itself decides whether it verified the email (e.g. a Gmail
    # address always is; some Workspace setups may not be). We refuse to
    # proceed on an unverified email rather than let it slip past our
    # own academic-domain check below.
    if not email or not payload.get('email_verified'):
        request.session['login_block_message'] = "Google account has no verified email."
        return redirect('accounts:login')

    user = User.objects.filter(google_id=google_sub).first()

    if user is None:
        # First Google sign-in for this account. Link to an existing
        # dev-login user sharing the same email if one exists (covers
        # test accounts made before Google sign-in existed); otherwise
        # create a fresh user with an unusable password, since they'll
        # only ever authenticate through Google.
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User(
                username=email,
                email=email,
                first_name=payload.get('given_name', '') or '',
                last_name=payload.get('family_name', '') or '',
            )
            user.set_unusable_password()
        user.google_id = google_sub
        user.save()

    block_message = get_block_message(user, timezone.now())
    if not block_message and not user.is_verified:
        block_message = get_verification_block_message(user.email)

    if block_message:
        request.session['login_block_message'] = block_message
        return redirect('accounts:login')

    if not user.is_verified:
        complete_verification(user)
        request.session['show_verified_notice'] = True

    login(request, user)

    profile = getattr(user, 'profile', None)
    if not profile or not profile.profile_setup_complete:
        return redirect('accounts:profile_setup')
    return redirect('social:home')


@login_required
def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@login_required
def profile_setup_view(request):
    # get_or_create so a first-time user has a Profile row to attach the
    # form to. gender has no sane default, so this is a throwaway
    # placeholder that gets overwritten the moment the form is submitted.
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={'display_name': request.user.username, 'gender': 'Male'},
    )

    # Editing an existing profile (via the "Edit Profile" button on
    # profile.html, which links here with ?edit=true) should skip the
    # celebration screen and land back on the profile instead — that
    # screen only makes sense for first-time setup. The GET query param
    # seeds it; the hidden `is_edit` field in the form carries it through
    # the POST, since GET params aren't available in a POST request.
    is_edit = request.GET.get('edit') == 'true' or request.POST.get('is_edit') == 'true'

    if request.method == 'POST':
        form = ProfileSetupForm(request.POST, instance=profile)
        if form.is_valid():
            interests = form.cleaned_data.pop('interests')

            profile = form.save(commit=False)
            if profile.auto_translate:
                profile.translate_into = profile.primary_language
            profile.profile_setup_complete = True
            profile.save()

            # Replace rather than diff — simplest correct behavior for a
            # setup wizard that can be revisited.
            UserInterest.objects.filter(user=request.user).delete()
            UserInterest.objects.bulk_create([
                UserInterest(user=request.user, interest=i) for i in interests
            ])

            if is_edit:
                return redirect('accounts:profile')

            return render(request, 'accounts/setup-complete.html', {
                'profile': profile,
                'interests': interests,
            })
    else:
        current_interest_ids = UserInterest.objects.filter(
            user=request.user
        ).values_list('interest_id', flat=True)

        initial_data = {'interests': Interest.objects.filter(id__in=current_interest_ids)}

        # gender is a required model field with no blank/null state — the
        # get_or_create default above has to put a placeholder ('Male')
        # in the row for a first-time user, purely to satisfy the
        # database. Without this override, that placeholder would show
        # as pre-selected before the user ever actually chose anything.
        # Only show the real saved gender when genuinely editing an
        # already-completed profile.
        if not profile.profile_setup_complete:
            initial_data['gender'] = ''

        form = ProfileSetupForm(instance=profile, initial=initial_data)

    return render(request, 'accounts/profile-setup.html', {
        'form': form,
        'is_edit': is_edit,
    })


@login_required
def profile_view(request):
    profile = request.user.profile
    engagement = getattr(request.user, 'engagement', None)

    interest_ids = UserInterest.objects.filter(
        user=request.user
    ).values_list('interest_id', flat=True)
    interests = Interest.objects.filter(id__in=interest_ids)

    badge_rows = get_badge_progress(request.user)
    earned_group_count = sum(1 for b in badge_rows if b['is_earned'])

    mission_rows = get_mission_progress(request.user)
    daily_missions = [m for m in mission_rows if m['mission'].frequency == 'daily']
    weekly_missions = [m for m in mission_rows if m['mission'].frequency == 'weekly']

    return render(request, 'accounts/profile.html', {
        'active_page': 'profile',
        'profile': profile,
        'engagement': engagement,
        'interests': interests,
        'badge_rows': badge_rows,
        'earned_group_count': earned_group_count,
        'total_badge_groups': len(badge_rows),
        'daily_missions': daily_missions,
        'weekly_missions': weekly_missions,
    })


@login_required
@require_POST
def update_display_name_view(request):
    name = request.POST.get('display_name', '').strip()
    if name:
        request.user.profile.display_name = name
        request.user.profile.save(update_fields=['display_name'])
    return redirect(reverse('accounts:profile') + '#accountSettingsCard')


@login_required
@require_POST
def toggle_auto_translate_view(request):
    profile = request.user.profile
    profile.auto_translate = not profile.auto_translate
    if profile.auto_translate and not profile.translate_into:
        profile.translate_into = profile.primary_language
    profile.save(update_fields=['auto_translate', 'translate_into'])
    return redirect(reverse('accounts:profile') + '#accountSettingsCard')


@login_required
@require_POST
def update_translate_into_view(request):
    profile = request.user.profile
    choice = request.POST.get('translate_into', '').strip()
    # Only accept one of the user's own two languages — prevents an
    # arbitrary string being written in from a manipulated request.
    if choice in (profile.primary_language, profile.secondary_language):
        profile.translate_into = choice
        profile.save(update_fields=['translate_into'])
    return redirect(reverse('accounts:profile') + '#accountSettingsCard')


@login_required
@require_POST
def delete_account_view(request):
    """
    Soft delete only — per the brief, never a hard DELETE.
    """
    user = request.user
    user.is_deleted = True
    user.deleted_at = timezone.now()
    user.is_active = False
    user.save(update_fields=['is_deleted', 'deleted_at', 'is_active'])

    # Cross-app cleanup so a deleted account doesn't leave live traps for
    # other, still-active students: releases any group seat they were
    # occupying (so it's not stuck "full" forever), and cancels any
    # pending MatchRequest involving them (so nobody can still Accept a
    # request from/to an account that no longer exists). See
    # matching/utils.py for both underlying functions.
    cleanup_matching_state_for_deleted_user(user)

    logout(request)
    return redirect('accounts:login')
