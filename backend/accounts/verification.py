import re

# Matches domains ending in .edu, .edu.<cc>, or .ac.<cc> (e.g. buet.ac.bd,
# mit.edu, monash.edu.au). Anchored to the end of the string so it only
# matches the suffix, not any substring elsewhere in the domain.
ACADEMIC_DOMAIN_PATTERN = re.compile(
    r"(\.edu(\.[a-z]{2,3})?|\.ac\.[a-z]{2,3})$", re.IGNORECASE
)

# Manual exceptions for real universities whose domains don't match the
# pattern above. Empty on purpose — add entries here as specific gaps
# turn up in real sign-up data, rather than guessing ahead of time.
ACADEMIC_DOMAIN_WHITELIST = set()

UNVERIFIED_EMAIL_MESSAGE = (
    "We couldn't verify your email as an academic address, so we can't "
    "sign you in yet. If you believe this is a mistake, contact support."
)


def extract_domain_from_email(email):
    """
    Returns the lowercased domain portion of an email address. Raises
    on anything that isn't a plausible email — callers should never
    silently proceed with a missing/malformed domain.
    """
    if not email or "@" not in email:
        raise ValueError(f"Cannot extract domain from invalid email: {email!r}")
    return email.rsplit("@", 1)[1].strip().lower()


def is_academic_domain(domain):
    """
    The actual verification gate. Deterministic on purpose — see the
    project's design notes: this decision needs to be instant, free,
    reproducible, and never dependent on an external API's uptime.
    """
    if not domain:
        return False
    domain = domain.strip().lower()
    if domain in ACADEMIC_DOMAIN_WHITELIST:
        return True
    return bool(ACADEMIC_DOMAIN_PATTERN.search(domain))


def get_verification_block_message(email):
    """
    Returns the sign-in block message if this email's domain fails the
    academic check, or None if it's fine to proceed. Only meant to be
    called for users who aren't verified yet — see complete_verification
    below for what happens once this passes.
    """
    domain = extract_domain_from_email(email)
    if is_academic_domain(domain):
        return None
    return UNVERIFIED_EMAIL_MESSAGE


def pop_verified_notice_flag(request):
    """
    Returns True exactly once — the first page rendered after
    complete_verification() runs — then clears the flag so a page
    refresh or a later visit never shows the modal again. A session
    flag was chosen over a DB field here on purpose: this is a one-time
    UI event, not account state worth persisting or migrating for.
    """
    return request.session.pop('show_verified_notice', False)


def complete_verification(user):
    """
    Called once, the first time a user passes the domain check. Marks
    the account verified and resolves their University row (creating it
    on first sign-up from a new domain — see
    ai_agents/services/verification_service.py for the naming logic).
    Only touches `university` if it isn't already set, so re-running
    this never overwrites an admin's manual correction.
    """
    from ai_agents.services.verification_service import resolve_university

    domain = extract_domain_from_email(user.email)
    user.is_verified = True
    if user.university is None:
        user.university = resolve_university(domain)
    user.save(update_fields=['is_verified', 'university'])
