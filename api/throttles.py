from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


# login and register, per IP
class AuthThrottle(AnonRateThrottle):
    scope = "auth"


# asking questions, per user
class QuestionThrottle(UserRateThrottle):
    scope = "question"


# arXiv searches, per user
class SearchThrottle(UserRateThrottle):
    scope = "search"
