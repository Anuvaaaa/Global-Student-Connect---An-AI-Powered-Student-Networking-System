from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)

        profile = getattr(user, 'profile', None)
        if not profile or not profile.profile_setup_complete:
            return redirect('accounts:profile_setup')
        return redirect('social:home')

    return render(request, 'accounts/index.html', {'form': form})


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

            return redirect('social:home')
    else:
        current_interest_ids = UserInterest.objects.filter(
            user=request.user
        ).values_list('interest_id', flat=True)
        form = ProfileSetupForm(
            instance=profile,
            initial={'interests': Interest.objects.filter(id__in=current_interest_ids)},
        )

    return render(request, 'accounts/profile-setup.html', {'form': form})


@login_required
def profile_view(request):
    profile = request.user.profile
    engagement = getattr(request.user, 'engagement', None)

    # No related_name was set on UserBadge/UserMissionProgress's user FK
    # (confirmed from the Phase 0 models — fine since each only has one FK
    # to User), so Django's default reverse accessors apply here.
    user_badges = (
        request.user.userbadge_set
        .select_related('badge')
        .order_by('badge__badge_group', 'badge__tier')
    )
    mission_progress = (
        request.user.usermissionprogress_set
        .select_related('mission')
    )

    interest_ids = UserInterest.objects.filter(
        user=request.user
    ).values_list('interest_id', flat=True)
    interests = Interest.objects.filter(id__in=interest_ids)

    return render(request, 'accounts/profile.html', {
        'active_page': 'profile',
        'profile': profile,
        'engagement': engagement,
        'user_badges': user_badges,
        'mission_progress': mission_progress,
        'interests': interests,
    })


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
    logout(request)
    return redirect('accounts:login')
