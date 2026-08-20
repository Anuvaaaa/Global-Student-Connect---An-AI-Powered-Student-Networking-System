from django.contrib.auth import get_user_model

from accounts.models import University
from accounts.models import Profile
from chat.models import Conversation
from matching.models import MatchRequest, Connection, StudentGroup, GroupMember

User = get_user_model()


def make_university(domain='test.edu', name='Test University'):
    return University.objects.create(domain=domain, name=name)


def make_user(username, university=None, is_verified=True, is_deleted=False,
              is_banned=False, password='testpass123'):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@test.edu',
        password=password,
    )
    user.university = university
    user.is_verified = is_verified
    user.is_deleted = is_deleted
    user.is_banned = is_banned
    user.save()
    return user


def make_profile(user, display_name='Test User', country='Bangladesh',
                  primary_language='Bengali', secondary_language='',
                  translate_into='English', auto_translate=False):
    return Profile.objects.create(
        user=user,
        display_name=display_name,
        country=country,
        primary_language=primary_language,
        secondary_language=secondary_language,
        auto_translate=auto_translate,
        translate_into=translate_into,
        profile_setup_complete=True,
    )


def make_connection(user_a, user_b, status='active'):
    match_request = MatchRequest.objects.create(
        requester=user_a, recipient=user_b, status='accepted'
    )
    return Connection.objects.create(
        match_request=match_request, user_a=user_a, user_b=user_b, status=status
    )


def make_direct_conversation(connection):
    return Conversation.objects.create(type='direct', connection=connection)


def make_group(name='Test Group'):
    return StudentGroup.objects.create(name=name)


def make_group_member(group, user, left_at=None):
    return GroupMember.objects.create(group=group, user=user, left_at=left_at)


def make_group_conversation(group):
    return Conversation.objects.create(type='group', group=group)
