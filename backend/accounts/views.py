from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from engagement.utils import get_badge_progress, get_mission_progress
from matching.utils import cleanup_matching_state_for_deleted_user
from social.models import Interest, UserInterest

from .forms import ProfileSetupForm
from .models import Profile


def login_view(request):
    """
    Fake username/password login (Person A Step 1) — NOT Google OAuth.
    Deliberately built first so the rest of the team can test without
    Cloud Console setup. Swap this for real Google sign-in later (Step 7)
    without touching profile_setup_view/profile_view at all — they only
    care that request.user is authenticated, not how.
    """
    if request.user.is_authenticated:
        return redirect('social:home')

    form = AuthenticationForm(request, data=request.POST or None)
    block_message = None

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()

        if user.is_banned:
            block_message = (
                "Your account has been permanently banned for violating "
                "community guidelines."
            )
        elif user.suspended_until and user.suspended_until > timezone.now():
            local_time = timezone.localtime(user.suspended_until)
            block_message = (
                "Your account is suspended until "
                f"{local_time.strftime('%B %d, %Y at %H:%M')} "
                "for violating community guidelines."
            )

        if block_message:
            return render(request, 'accounts/index.html', {
                'form': form,
                'block_message': block_message,
            })

        login(request, user)

        profile = getattr(user, 'profile', None)
        if not profile or not profile.profile_setup_complete:
            return redirect('accounts:profile_setup')
        return redirect('social:home')

    return render(request, 'accounts/index.html', {'form': form, 'block_message': block_message})


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
