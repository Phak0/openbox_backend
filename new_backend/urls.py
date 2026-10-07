# main/new_backend/urls.py
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (RegisterView, VerifyEmailView, UserProfileView, BoxListView, InitializeDepositView, VerifyDepositView, HardwareTestPrintView, GoogleSignInView, CubbyConversationHistoryView, InstantPrintConversationHistoryView, ConversationListView, ConversationDetailView,
    ConversationActionView, RecentTasksView, TaskHistoryView, TaskHistoryDetailView, TaskBoxStatusView, AddDocumentToStoredPrintView, WalletTransactionHistoryView, hardware_test_ui, StartPrintTaskView, StartStorageTaskView, PackageAccessRedeemView, SimulateBoxStatusView)

from .views_private_cubby import CubbyStatusView, ApplyForCubbyView, SetupCubbyView, GenerateTemporaryPinView, RevokeTemporaryPinView, VerifyTemporaryPinView, ShareCubbyView, SharedUsersView, RevokeSharedAccessView, CubbyActivityView

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth_register'),
    path('auth/verify-email/', VerifyEmailView.as_view(), name='verify_email'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/google/', csrf_exempt(GoogleSignInView.as_view()), name='google-signup'),
    path('profile/', UserProfileView.as_view(), name='user_profile'),
    path('boxes/', BoxListView.as_view(), name='box_list'),
    path('auth/tasks/start/', StartPrintTaskView.as_view(), name='task_start'),
    path(
    "tasks/start-storage/",
    StartStorageTaskView.as_view(),
    name="start-storage-task",
    ),
    path(
    "package-access/<str:token>/",
    PackageAccessRedeemView.as_view(),
    ),
    
    
    path('wallet/deposit/initialize/', InitializeDepositView.as_view(), name='deposit_initialize'),
    path('wallet/deposit/verify/', VerifyDepositView.as_view(), name='deposit_verify'),
    path('user/profile/', UserProfileView.as_view(), name='user_profile'),

    path('test/box-status/', SimulateBoxStatusView.as_view(), name='simulate_box_status'),
    path("tasks/<int:task_id>/box-status/", TaskBoxStatusView.as_view(), name="task-box-status"),

    path("tasks/<int:task_id>/documents/add/", AddDocumentToStoredPrintView.as_view(), name="add-document-to-stored-print"),

    #///////////////////////////////////////////////////
    path(
        "cubbies/<int:cubby_id>/conversations/",
        CubbyConversationHistoryView.as_view(),
        name="cubby-conversation-history",
    ),
    path(
        "conversations/instant-print/",
        InstantPrintConversationHistoryView.as_view(),
        name="instant-print-conversation-history",
    ),

    path(
        "conversations/",
        ConversationListView.as_view(),
        name="conversation-list",
    ),
    path(
        'conversations/<int:session_id>/',
        ConversationDetailView.as_view(),
        name='conversation-detail',
    ),
    path(
        'conversations/<int:session_id>/action/',
        ConversationActionView.as_view(),
        name='conversation-action',
    ),
    path(
        'dashboard/recent-tasks/',
        RecentTasksView.as_view(),
        name='recent-tasks',
    ),
    path(
        'dashboard/history/',
        TaskHistoryView.as_view(),
        name='task-history',
    ),
    path(
    'dashboard/history/<int:pk>/',
    TaskHistoryDetailView.as_view(),
    name='task-history-detail',
    ),
    path(
    'wallet/transactions/',
    WalletTransactionHistoryView.as_view(),
    name='wallet-transactions',
),



    #///////////////////////////////////////////////////

    # The endpoint that receives the file
    path('api/hardware-test/', HardwareTestPrintView.as_view(), name='hardware-test'),
    
    # The endpoint that shows the webpage UI to the testers
    path('test-ui/', hardware_test_ui, name='test-ui'),
]


urlpatterns += [
    path('cubby/status', CubbyStatusView.as_view()),
    path('cubby/apply', ApplyForCubbyView.as_view()),
    path('cubby/setup', SetupCubbyView.as_view()),
    path('cubby/temp-pin', GenerateTemporaryPinView.as_view()),
    path('cubby/temp-pin/<int:pin_id>/revoke', RevokeTemporaryPinView.as_view()),
    path('cubby/<str:cubby_code>/verify-pin', VerifyTemporaryPinView.as_view()),
    path('cubby/share', ShareCubbyView.as_view()),
    path('cubby/shared-users', SharedUsersView.as_view()),
    path('cubby/shared-users/<int:access_id>/revoke', RevokeSharedAccessView.as_view()),
    path('cubby/activity', CubbyActivityView.as_view()),
]