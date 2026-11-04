# main/new_backend/urls.py
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (RegisterView, VerifyEmailView, FirebaseTokenView, UserProfileView, BoxListView, StationListView, StationCreateView, StationDetailView, StationLoginView, StationMeView, StartStationPrintTaskView, UserRecentStationsView, StationTaskListView, StationTaskPacketDownloadView, StationTaskStatusUpdateView, InitializeDepositView, VerifyDepositView, HardwareTestPrintView, GoogleSignInView, CubbyConversationHistoryView, InstantPrintConversationHistoryView, StationConversationListView, ConversationListView, ConversationDetailView,
    ConversationActionView, DashboardRecentTasksView, AllTasksView, TaskHistoryView, TaskHistoryDetailView, TaskBoxStatusView, AddDocumentToStoredPrintView, WalletTransactionHistoryView, hardware_test_ui, StartPrintTaskView, StartStorageTaskView, PackageAccessRedeemView, BoxTaskStatusUpdateAPIView, BoxTaskDownloadView, BoxClaimInstantPrintTaskView)

from .views_private_cubby import CubbyStatusView, ApplyForCubbyView, SetupCubbyView, GenerateTemporaryPinView, RevokeTemporaryPinView, VerifyTemporaryPinView, ShareCubbyView, SharedUsersView, RevokeSharedAccessView, CubbyActivityView

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth_register'),
    path('auth/verify-email/', VerifyEmailView.as_view(), name='verify_email'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/google/', csrf_exempt(GoogleSignInView.as_view()), name='google-signup'),
    path('auth/firebase-token/', FirebaseTokenView.as_view(), name='firebase_token'),
    path('profile/', UserProfileView.as_view(), name='user_profile'),
    path('boxes/', BoxListView.as_view(), name='box_list'),


    #//------STATION RELATED ENDPOINTS------
    path('stations/', StationListView.as_view(), name='station-list'),
    path('stations/create/', StationCreateView.as_view(), name='station-create'),
    path('stations/login/', StationLoginView.as_view(), name='station-login'),
    path('stations/me/', StationMeView.as_view(), name='station-me'),
    path('station/me/', StationMeView.as_view(), name='station-me-alias'),
    path('stations/<int:pk>/', StationDetailView.as_view(), name='station-detail'),
    path('stations/tasks/start-print/', StartStationPrintTaskView.as_view(), name='start-station-print'),
    path('stations/recent/', UserRecentStationsView.as_view(), name='user-recent-stations'),
    path('station/recent/', UserRecentStationsView.as_view(), name='user-recent-stations-alias'),
    path('station/tasks/', StationTaskListView.as_view(), name='station-task-list'),
    path('station/tasks/<int:task_id>/packet/', StationTaskPacketDownloadView.as_view(), name='station-task-packet'),
    path('station/tasks/<int:task_id>/status/', StationTaskStatusUpdateView.as_view(), name='station-task-status-update'),
    #//--------------------------------------------------//


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

    path('test/box-status/', BoxTaskStatusUpdateAPIView.as_view(), name='box-task-status-update'),
    path("box/claim-instant-print/", BoxClaimInstantPrintTaskView.as_view(), name="box-claim-instant-print",),
    path('box/tasks/<int:task_id>/download/', BoxTaskDownloadView.as_view(), name='box-task-download'),
    path("tasks/<int:task_id>/box-status/", TaskBoxStatusView.as_view(), name="task-box-status"),

    path("tasks/<int:task_id>/documents/add/", AddDocumentToStoredPrintView.as_view(), name="add-document-to-stored-print"),

    #///////////////////////////////////////////////////
    path(
        "cubbies/<int:cubby_id>/conversations/",
        CubbyConversationHistoryView.as_view(),
        name="cubby-conversation-history",
    ),
    path(
        'stations/<int:station_id>/conversations/', 
        StationConversationListView.as_view(), 
        name='station-conversations'
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
        DashboardRecentTasksView.as_view(),
        name='recent-tasks',
    ),
    path(
        'all-tasks/',
        AllTasksView.as_view(),
        name='all-tasks',
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