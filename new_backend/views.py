import random
import requests
import math
import uuid
import os
import json
import zipfile
import secrets
import hashlib
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.auth.transport import requests as google_requests
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from django.core.mail import send_mail
from decimal import Decimal
from django.utils import duration, timezone
from django.db import transaction
from django.db.models import Count
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status, generics
from google.oauth2 import id_token
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from permissions import IsAuthenticatedBox
from .firebase_service import (
    create_task_in_firestore,
    update_box_status_in_firestore,
    update_task_assignment_in_firestore,
    update_task_status_in_firestore,
    generate_firebase_custom_token
)
from rest_framework.pagination import PageNumberPagination
from .models import (Box, Station, WaitlistEntry, Deposit, Cubby, PrivateCubby, PrivateCubbyApplication, Task, PrintDocument, PendingPrintDocument, ConversationSession, ConversationMessage)
from .serializers import (
    UserRegistrationSerializer, 
    UserProfileSerializer, 
    BoxListSerializer,
    StationSerializer,
    StationDetailSerializer,
    StationRegistrationSerializer,
    StationUpdateSerializer,
    ConversationSerializer,
    ConversationActionSerializer,
    ConversationSummarySerializer,
    RecentTaskSerializer,
    TaskHistorySerializer,
    BoxTaskDownloadSerializer,
    WalletTransactionSerializer
)
from .services import ConversationService, WalletService, PricingService
from .models import User, Box, Cubby, Task, ConversationSession, WalletTransaction
from django.shortcuts import get_object_or_404, render
from datetime import timedelta
from django.db.models import Q, OuterRef, Subquery, Max, Prefetch
from io import BytesIO
from PIL import Image
from PyPDF2 import PdfReader
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.urls import reverse
from django.contrib.auth.hashers import make_password
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import RetrieveAPIView, ListAPIView
from rest_framework.decorators import api_view, permission_classes
from .station_authentication import StationAuthentication, StationAPIKeyAuthentication, IsAuthenticatedStation, generate_station_token



class RegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # 1. Generate a 6-digit verification code
            verification_code = str(random.randint(100000, 999999))
            
            # 2. Save it to the user's database record
            user.verification_code = verification_code
            user.save()

            # 3. Send the Email
            subject = "Verify your OpenBox Account"
            message = f"Hello {user.name},\n\nWelcome to OpenBox! Your verification code is: {verification_code}\n\nPlease enter this code in the app to activate your account."
            from_email = "noreply@openbox.com"
            recipient_list = [user.email]

            send_mail(subject, message, from_email, recipient_list)
            
            return Response({
                "message": "User created. Please check your email for the verification code.",
                "user_code": user.user_code
            }, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class VerifyEmailView(APIView):
    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        
        try:
            user = User.objects.get(email=email, verification_code=code)
            user.is_verified = True
            user.verification_code = None  # Clear it once used for security
            user.save()
            return Response({"message": "Email verified successfully!"}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "Invalid code or email"}, status=status.HTTP_400_BAD_REQUEST)
        
class GoogleSignInView(APIView):
    # Completely bypasses CSRF and token checks
    authentication_classes = []
    # This endpoint shouldn't require authentication to access
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Verify the token with Google (Ensure your real client ID is here)
            id_info = id_token.verify_oauth2_token(
                token, 
                GoogleAuthRequest(), 
                '362958356322-mmoc28okm2iq61omf6vt36kl158g9vk7.apps.googleusercontent.com' 
            )
            
            # Google verified! Extract user info
            email = id_info.get('email')
            first_name = id_info.get('given_name', '')
            last_name = id_info.get('family_name', '')

            # Combine Google's first/last name into your custom 'name' field
            full_name = f"{first_name} {last_name}".strip()

            # 1. Generate the unique code AHEAD of time
            unique_user_code = f"G-{uuid.uuid4().hex[:6].upper()}"

            # 2. Use 'defaults' so these values are included in the initial database INSERT query
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'name': full_name,
                    'user_code': unique_user_code,
                }
            )
            
            if created:
                # Set unusable password since they authenticate via Google
                user.set_unusable_password() 
                user.save()

            # Generate JWT tokens for your React frontend
            refresh = RefreshToken.for_user(user)
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'email': user.email
            }, status=status.HTTP_200_OK)

        except ValueError:
            # Token was invalid
            return Response({'error': 'Invalid Google Token'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def join_waitlist(request):
    email = request.data.get('email')
    
    if not email:
        return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        
    if WaitlistEntry.objects.filter(email=email).exists():
        return Response(
            {"message": "You're already on the waitlist! We'll be in touch soon."}, 
            status=status.HTTP_200_OK
        )
        
    WaitlistEntry.objects.create(email=email)
    
    subject = "You're on the OpenBox Waitlist!"
    message = (
        "Hi there,\n\n"
        "Thanks for joining the OpenBox waitlist! "
        "We will notify you as soon as testing is complete and the platform goes live.\n\n"
        "Best,\n"
        "The OpenBox Team"
    )
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"Failed to send waitlist email to {email}: {e}")
        
    return Response({"message": "Successfully joined the waitlist!"}, status=status.HTTP_201_CREATED)


class FirebaseTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        firebase_token = generate_firebase_custom_token(
            request.user
        )

        return Response({
            "firebase_token": firebase_token
        }, status=status.HTTP_200_OK)       

class UserProfileView(APIView):
    # This single line is the bouncer. It blocks anyone without a valid token!
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Because the user is authenticated, Django automatically knows WHO they are.
        user = request.user 
        
        return Response({
            "name": user.name,
            "email": user.email,
            "user_type": user.user_type,
            "message": "Success! You have accessed a protected route."
        }, status=status.HTTP_200_OK)
    
class BoxListView(generics.ListAPIView):
    """Fetches all available boxes, optionally sorting by distance if lat/lon are provided."""
    serializer_class = BoxListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Box.objects.filter(is_available=True)
        
        user_lat = self.request.query_params.get('lat')
        user_lon = self.request.query_params.get('lon')

        if user_lat and user_lon:
            try:
                u_lat = float(user_lat)
                u_lon = float(user_lon)
                
                # Calculate distance for each box
                boxes = list(queryset)
                for box in boxes:
                    box.distance = calculate_haversine(u_lat, u_lon, float(box.latitude), float(box.longitude))
                
                # Sort by closest first
                boxes.sort(key=lambda x: x.distance)
                return boxes
            except ValueError:
                pass # If they send bad data, just return the default unsorted list

        return queryset


# 1. LIST STATIONS (With Haversine distance sorting)
# -------------------------------------------------
class StationListView(generics.ListAPIView):
    """Fetches all available stations, optionally sorting by distance."""
    serializer_class = StationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Station.objects.filter(is_available=True, is_active=True)
        
        user_lat = self.request.query_params.get('lat')
        user_lon = self.request.query_params.get('lon')

        if user_lat and user_lon:
            try:
                u_lat = float(user_lat)
                u_lon = float(user_lon)
                
                stations = list(queryset)
                for station in stations:
                    if station.latitude is None or station.longitude is None:
                        station.distance = None
                    else:
                        station.distance = calculate_haversine(
                            u_lat, u_lon, float(station.latitude), float(station.longitude)
                        )
                stations.sort(key=lambda x: x.distance if x.distance is not None else float('inf'))
                return stations
            except ValueError:
                pass 

        return queryset

# -------------------------------------------------
# 2. RETRIEVE STATION DETAILS
# -------------------------------------------------
class StationDetailView(generics.RetrieveAPIView):
    """Fetches specific info for a single station."""
    queryset = Station.objects.all()
    serializer_class = StationDetailSerializer
    permission_classes = [IsAuthenticated]

# -------------------------------------------------
# 3. CREATE STATION (Any authenticated user)
# -------------------------------------------------
class StationCreateView(generics.CreateAPIView):
    """Register a private printing station and issue its one-time API key and web JWT."""
    queryset = Station.objects.all()
    serializer_class = StationRegistrationSerializer
    authentication_classes = []
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        station = serializer.save()

        raw_api_key = "stn_" + secrets.token_urlsafe(40)
        station.api_key_hash = hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
        station.save(update_fields=["api_key_hash", "updated_at"])

        token = generate_station_token(station)

        return Response({
            "message": "Station registered successfully.",
            "station": StationDetailSerializer(station).data,
            "token": token,
            "api_key": raw_api_key,
            "authentication": "Authorization: Bearer <api_key_or_token>",
        }, status=status.HTTP_201_CREATED)


class StationLoginView(APIView):
    """Station owner login via email or unique station name + password."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = str(request.data.get('email', request.data.get('identifier', request.data.get('login', '')))).strip()
        password = str(request.data.get('password', ''))

        if not identifier or not password:
            return Response({'error': 'Email/Station Name and Password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        station = Station.objects.filter(
            Q(email__iexact=identifier) | Q(name__iexact=identifier)
        ).first()

        if not station or not station.check_password(password):
            return Response({'error': 'Invalid credentials. Please verify your email/station name and password.'}, status=status.HTTP_400_BAD_REQUEST)

        if not station.is_active:
            return Response({'error': 'This station is currently deactivated.'}, status=status.HTTP_403_FORBIDDEN)

        station.last_seen_at = timezone.now()
        station.save(update_fields=['last_seen_at'])

        token = generate_station_token(station)

        return Response({
            'message': 'Login successful.',
            'token': token,
            'station': StationDetailSerializer(station).data,
        }, status=status.HTTP_200_OK)


class StationMeView(APIView):
    """View and update authenticated station profile (address, pricing, availability)."""
    authentication_classes = [StationAuthentication]
    permission_classes = [IsAuthenticatedStation]

    def get(self, request):
        station = request.auth if isinstance(request.auth, Station) else request.user
        return Response(StationDetailSerializer(station).data)

    def patch(self, request):
        station = request.auth if isinstance(request.auth, Station) else request.user
        serializer = StationUpdateSerializer(station, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': 'Station profile updated successfully.',
            'station': StationDetailSerializer(station).data
        })


class UserRecentStationsView(APIView):
    """
    Returns up to 3 distinct stations that the authenticated user has used in the past.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        station_ids = list(
            Task.objects
            .filter(user=request.user, station__isnull=False)
            .order_by('-created_at')
            .values_list('station_id', flat=True)
        )
        seen = set()
        recent_ids = []
        for sid in station_ids:
            if sid not in seen:
                seen.add(sid)
                recent_ids.append(sid)
                if len(recent_ids) >= 3:
                    break

        stations = Station.objects.filter(id__in=recent_ids, is_active=True)
        station_dict = {s.id: s for s in stations}
        ordered_stations = [station_dict[sid] for sid in recent_ids if sid in station_dict]

        return Response(StationSerializer(ordered_stations, many=True).data)


class StartStationPrintTaskView(APIView):
    """Create a paid-through-conversation print task for a selected private station."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        station_id = request.data.get('station_id')
        uploaded_file = request.FILES.get('file')
        if not station_id:
            return Response({'error': 'station_id is required.'}, status=400)
        station = get_object_or_404(Station, id=station_id, is_active=True)
        if not station.is_available:
            return Response({'error': 'This station is currently unavailable.'}, status=400)
        if not uploaded_file:
            return Response({'error': 'File is required for printing.'}, status=400)

        try:
            copies = int(request.data.get('copies', 1))
            if copies < 1 or copies > 100:
                raise ValueError
        except (TypeError, ValueError):
            return Response({'error': 'Copies must be an integer between 1 and 100.'}, status=400)

        color_mode = str(request.data.get('color_mode', 'color')).lower()
        if color_mode not in {'color', 'colour', 'black_and_white', 'grayscale', 'greyscale', 'monochrome'}:
            return Response({'error': 'Invalid color_mode.'}, status=400)
        color_mode = 'black_and_white' if color_mode in {'grayscale', 'greyscale', 'monochrome'} else ('color' if color_mode == 'colour' else color_mode)

        duplex_raw = str(request.data.get('duplex', 'false')).lower()
        if duplex_raw in {'true', '1', 'yes', 'on', 'double-sided', 'double_sided'}:
            duplex = True
        elif duplex_raw in {'false', '0', 'no', 'off', 'single-sided', 'single_sided'}:
            duplex = False
        else:
            return Response({'error': 'duplex must be a boolean value.'}, status=400)

        orientation = str(request.data.get('orientation', 'portrait')).lower()
        if orientation not in {'portrait', 'landscape'}:
            return Response({'error': 'orientation must be portrait or landscape.'}, status=400)

        extension = os.path.splitext(uploaded_file.name.lower())[1]
        if extension not in {'.pdf', '.png', '.jpg', '.jpeg'}:
            return Response({'error': 'Unsupported file type. Allowed formats: PDF, PNG, JPG, JPEG.'}, status=400)

        if extension == '.pdf':
            try:
                reader = PdfReader(uploaded_file)
                page_count = len(reader.pages)
                if page_count < 1:
                    raise ValueError('PDF contains no pages')
            except Exception:
                return Response({'error': 'The uploaded file is not a valid PDF.'}, status=400)
        else:
            page_count = 1
        uploaded_file.seek(0)

        total_printed_pages = page_count * copies
        if total_printed_pages > 100:
            return Response({'error': 'A print task cannot exceed 100 printed pages.', 'total_printed_pages': total_printed_pages}, status=400)

        print_settings = {
            'color_mode': color_mode,
            'duplex': duplex,
            'orientation': orientation,
        }
        amount = Decimal(total_printed_pages) * station.printing_price

        with transaction.atomic():
            task = Task.objects.create(
                user=request.user,
                box=None,
                cubby=None,
                station=station,
                task_type=Task.TaskType.INSTANT_PRINT,
                status=Task.Status.PENDING,
                box_status=Task.BoxStatus.QUEUED,
                amount=amount,
                task_data={
                    'document_name': uploaded_file.name,
                    'pages': page_count,
                    'copies': copies,
                    **print_settings,
                    'print_type': 'station_instant',
                    'total_printed_pages': total_printed_pages,
                    'station_id': station.id,
                },
            )
            PrintDocument.objects.create(
                task=task,
                file=uploaded_file,
                original_filename=uploaded_file.name,
                page_count=page_count,
                copies=copies,
                print_settings=print_settings,
                amount=amount,
            )
            conversation = ConversationService.create_session(task)

        return Response({
            'task_id': task.id,
            'conversation_id': conversation.id,
            'station': {'id': station.id, 'name': station.name},
            'amount': str(amount),
            'currency': 'NGN',
            'status': task.status,
            'message': 'Station print task created. The station can retrieve it after payment is completed.',
        }, status=status.HTTP_201_CREATED)


class StationTaskListView(APIView):
    """Return tasks assigned to the authenticated station."""
    authentication_classes = [StationAuthentication]
    permission_classes = [IsAuthenticatedStation]

    def get(self, request):
        station = request.auth if isinstance(request.auth, Station) else request.user
        filter_status = request.query_params.get('status', 'active').lower()

        queryset = (Task.objects.filter(station=station)
                    .prefetch_related('documents')
                    .select_related('user')
                    .order_by('-created_at'))

        # Station owner only sees tasks after the user completes payment!
        queryset = queryset.exclude(status=Task.Status.PENDING)

        if filter_status == 'active':
            queryset = queryset.filter(
                status=Task.Status.ACTIVE,
                box_status__in=[
                    Task.BoxStatus.QUEUED,
                    Task.BoxStatus.RECEIVED,
                    Task.BoxStatus.PROCESSING,
                    Task.BoxStatus.PRINTING,
                    Task.BoxStatus.NOT_SENT,
                ]
            )
        elif filter_status == 'completed':
            queryset = queryset.filter(box_status=Task.BoxStatus.COMPLETED)
        elif filter_status in ['declined', 'failed']:
            queryset = queryset.filter(box_status=Task.BoxStatus.FAILED)

        results = []
        for task in queryset:
            documents = []
            for document in task.documents.all():
                file_url = None
                if document.file:
                    try:
                        file_url = request.build_absolute_uri(document.file.url)
                    except Exception:
                        file_url = f"/media/{document.file.name}"

                documents.append({
                    'id': document.id,
                    'document_name': document.original_filename or os.path.basename(document.file.name),
                    'page_count': document.page_count,
                    'copies': document.copies,
                    'print_settings': document.print_settings or {},
                    'file_url': file_url,
                })
            packet_path = reverse('station-task-packet', kwargs={'task_id': task.id})
            primary_doc = documents[0] if documents else {}
            results.append({
                'id': task.id,
                'task_id': task.id,
                'access_code': task.access_code,
                'user_name': task.user.name if task.user else 'Customer',
                'user_email': task.user.email if task.user else '',
                'document_name': primary_doc.get('document_name') or (task.task_data or {}).get('document_name', 'Document'),
                'file_url': primary_doc.get('file_url'),
                'documents': documents,
                'print_settings': primary_doc.get('print_settings') or {},
                'task_data': task.task_data or {},
                'task_status': task.status,
                'station_status': task.box_status,
                'amount': str(task.amount),
                'created_at': task.created_at,
                'completed_at': task.completed_at,
                'packet_download_url': request.build_absolute_uri(packet_path),
            })
        return Response({'station_id': station.id, 'count': len(results), 'tasks': results})


class StationTaskPacketDownloadView(APIView):
    """Build a ZIP containing each original document and task.json."""
    authentication_classes = [StationAuthentication]
    permission_classes = [IsAuthenticatedStation]

    def get(self, request, task_id):
        station = request.auth if isinstance(request.auth, Station) else request.user
        task = get_object_or_404(
            Task.objects.prefetch_related('documents'),
            id=task_id,
            station=station,
        )
        buffer = BytesIO()
        packet_documents = []
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for index, document in enumerate(task.documents.all(), start=1):
                if not document.file:
                    continue
                filename = os.path.basename(document.original_filename or document.file.name) or f'document_{index}'
                archive_name = f'documents/{index}_{filename}'
                document.file.open('rb')
                try:
                    archive.writestr(archive_name, document.file.read())
                finally:
                    document.file.close()
                packet_documents.append({
                    'document_name': filename,
                    'file': archive_name,
                    'page_count': document.page_count,
                    'copies': document.copies,
                    'print_settings': document.print_settings or {},
                })

            packet = {
                'task_id': task.id,
                'access_code': task.access_code,
                'task_type': task.task_type,
                'task_status': task.status,
                'station': {'id': station.id, 'name': station.name},
                'created_at': task.created_at.isoformat(),
                'task_data': task.task_data or {},
                'documents': packet_documents,
            }
            archive.writestr('task.json', json.dumps(packet, indent=2, default=str))

        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="station_task_{task.id}.zip"'
        response['Content-Length'] = str(buffer.getbuffer().nbytes)
        return response


class StationTaskStatusUpdateView(APIView):
    """Accept accept/decline/complete/status reports from the station that owns the task."""
    authentication_classes = [StationAuthentication]
    permission_classes = [IsAuthenticatedStation]

    @transaction.atomic
    def patch(self, request, task_id):
        station = request.auth if isinstance(request.auth, Station) else request.user
        task = get_object_or_404(Task.objects.select_for_update(), id=task_id, station=station)
        
        action = request.data.get('action') # 'accept', 'decline', 'complete'
        new_status = request.data.get('station_status', request.data.get('box_status'))

        if action == 'accept':
            new_status = Task.BoxStatus.RECEIVED
        elif action == 'decline':
            new_status = Task.BoxStatus.FAILED
        elif action == 'complete':
            new_status = Task.BoxStatus.COMPLETED

        allowed = {
            Task.BoxStatus.QUEUED, Task.BoxStatus.RECEIVED,
            Task.BoxStatus.PROCESSING, Task.BoxStatus.PRINTING,
            Task.BoxStatus.COMPLETED, Task.BoxStatus.FAILED,
        }
        if new_status not in allowed:
            return Response({'error': 'Invalid station_status or action.', 'allowed': sorted(allowed)}, status=400)

        terminal_statuses = {Task.BoxStatus.COMPLETED, Task.BoxStatus.FAILED}
        if task.box_status in terminal_statuses and new_status != task.box_status:
            return Response({'error': 'This task is already in a terminal state.'}, status=409)

        changed = task.box_status != new_status
        if changed:
            task.box_status = new_status
            update_fields = ['box_status', 'updated_at']

            session = ConversationSession.objects.filter(task=task).order_by('-id').first()

            if new_status == Task.BoxStatus.COMPLETED:
                task.status = Task.Status.COMPLETED
                task.completed_at = timezone.now()
                update_fields.extend(['status', 'completed_at'])
                if session:
                    ConversationService._add_system_message(
                        session,
                        {
                            "title": "Printing Completed",
                            "message": f"Your document has been printed and is ready for pickup at {station.name}!",
                            "station_name": station.name,
                            "address": station.address,
                        },
                        message_type=ConversationMessage.MessageType.STATUS
                    )
                    ConversationService._complete_conversation(session)

            elif new_status == Task.BoxStatus.FAILED: # Declined or failed
                task.status = Task.Status.FAILED
                update_fields.append('status')
                # Refund user wallet if charged
                if task.amount > 0 and task.user:
                    try:
                        WalletService.refund(
                            user=task.user,
                            amount=task.amount,
                            task=task,
                        )
                    except Exception as e:
                        logger.exception(f"Refund failed for task {task.id}: {e}")
                if session:
                    ConversationService._add_system_message(
                        session,
                        {
                            "title": "Print Order Declined",
                            "message": f"The shop owner at {station.name} declined this print order. If charged, ₦{task.amount} has been refunded to your wallet.",
                            "declined": True,
                        },
                        message_type=ConversationMessage.MessageType.STATUS
                    )
                    ConversationService._complete_conversation(session)

            elif new_status == Task.BoxStatus.RECEIVED: # Accepted
                if task.status == Task.Status.PENDING:
                    task.status = Task.Status.ACTIVE
                    update_fields.append('status')
                if session:
                    ConversationService._add_system_message(
                        session,
                        {
                            "title": "Order Accepted",
                            "message": f"The shop owner at {station.name} accepted your document and is preparing the print job.",
                            "accepted": True,
                        },
                        message_type=ConversationMessage.MessageType.STATUS
                    )

            elif new_status == Task.BoxStatus.PRINTING: # Printing in progress on physical printer
                if task.status == Task.Status.PENDING:
                    task.status = Task.Status.ACTIVE
                    update_fields.append('status')
                if session:
                    ConversationService._add_system_message(
                        session,
                        {
                            "title": "Printing Started",
                            "message": f"Your document is being printed on the physical printer at {station.name}.",
                            "printing": True,
                        },
                        message_type=ConversationMessage.MessageType.STATUS
                    )

            task.save(update_fields=update_fields)
            if not session:
                ConversationService.add_box_status_message(task, new_status)
            try:
                from .firebase_service import update_box_status_in_firestore, update_task_in_firestore
                update_box_status_in_firestore(task)
                update_task_in_firestore(task)
            except Exception:
                pass

        return Response({
            'message': f'Task status updated to {task.box_status}.',
            'task_id': task.id,
            'station_status': task.box_status,
            'task_status': task.status,
        })

#///////////////////////////////////////////////////////////////////

class StartPrintTaskView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        box_id = request.data.get('box_id')
        print_type = request.data.get('print_type')
        copies = request.data.get('copies', 1)
        storage_hours = request.data.get('storage_hours')
        uploaded_file = request.FILES.get('file')

        # -----------------------------------------
        # Validate basic request
        # -----------------------------------------

        if not uploaded_file:
            return Response(
                {'error': 'File is required for printing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if print_type not in ['instant', 'stored']:
            return Response(
                {
                    'error': (
                        'Invalid print_type. '
                        'Use "instant" or "stored".'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            copies = int(copies)
        except (TypeError, ValueError):
            return Response(
                {'error': 'Copies must be a valid number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if copies < 1:
            return Response(
                {'error': 'Copies must be at least 1.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


        # -----------------------------------------
        # Validate file type + determine page count
        # -----------------------------------------

        allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg'}

        file_name = uploaded_file.name.lower()
        extension = os.path.splitext(file_name)[1]

        if extension not in allowed_extensions:
            return Response(
                {
                    'error': (
                        'Unsupported file type. '
                        'Allowed formats: PDF, PNG, JPG, JPEG.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # PDF page count
        if extension == '.pdf':
            try:
                reader = PdfReader(uploaded_file)
                page_count = len(reader.pages)
            except Exception:
                return Response(
                    {'error': 'The uploaded file is not a valid PDF.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Images count as one page
        else:
            page_count = 1

        uploaded_file.seek(0)

        if page_count < 1:
            return Response(
                {'error': 'The uploaded file contains no printable pages.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------------
        # Validate 100-page limit
        # -----------------------------------------

        total_printed_pages = page_count * copies

        if total_printed_pages > 100:
            return Response(
                {
                    'error': (
                        'A print task cannot exceed '
                        '100 printed pages.'
                    ),
                    'page_count': page_count,
                    'copies': copies,
                    'total_printed_pages': total_printed_pages,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -------------------------------------------------
        # INSTANT PRINT
        # -------------------------------------------------

        if print_type == "instant":
            amount = PricingService.calculate_instant_print_cost(
                pages=page_count,
                copies=copies,
            )

            with transaction.atomic():
                task = Task.objects.create(
                    user=request.user,
                    box=None,
                    cubby=None,
                    task_type=Task.TaskType.INSTANT_PRINT,
                    status=Task.Status.PENDING,
                    box_status=Task.BoxStatus.NOT_SENT,
                    amount=amount,
                    task_data={
                        "copies": copies,
                        "print_type": "instant",
                        "page_count": page_count,
                        "total_printed_pages": total_printed_pages,
                    },
                )

                PrintDocument.objects.create(
                    task=task,
                    file=uploaded_file,
                    original_filename=uploaded_file.name,
                    page_count=page_count,
                    copies=copies,
                    print_settings={
                        "print_type": "instant",
                    },
                    amount=amount,
                )

                conversation = ConversationService.create_session(
                    task
                )

            return Response(
                {
                    "task_id": task.id,
                    "conversation_id": conversation.id,
                },
                status=status.HTTP_201_CREATED,
            )

        # -------------------------------------------------
        # STORED PRINT
        # -------------------------------------------------

        if not box_id:
            return Response(
                {"error": "Box is required for stored printing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        box = get_object_or_404(Box, id=box_id)

        if not box.is_available:
            return Response(
                {"error": "This box is currently unavailable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not box.supports_printing:
            return Response(
                {"error": "This box does not support printing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not storage_hours:
            return Response(
                {"error": "storage_hours is required for stored printing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        storage_hours = int(storage_hours)

        if storage_hours < 1:
            return Response(
                {"error": "storage_hours must be at least 1."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = PricingService.calculate_print_cost(
            box=box,
            pages=page_count,
            copies=copies,
            is_stored=True,
            storage_hours=storage_hours,
        )

        with transaction.atomic():
            task = Task.objects.create(
                user=request.user,
                box=box,
                cubby=None,
                task_type=Task.TaskType.STORED_PRINT,
                status=Task.Status.PENDING,
                box_status=Task.BoxStatus.NOT_SENT,
                amount=amount,
                task_data={
                    "copies": copies,
                    "print_type": "stored",
                    "storage_hours": storage_hours,
                    "page_count": page_count,
                    "total_printed_pages": total_printed_pages,
                },
            )

            PrintDocument.objects.create(
                task=task,
                file=uploaded_file,
                original_filename=uploaded_file.name,
                page_count=page_count,
                copies=copies,
                print_settings={
                    "print_type": "stored",
                },
                amount=(
                    Decimal(total_printed_pages)
                    * (box.printing_price or Decimal("0.00"))
                ),
            )

            conversation = ConversationService.create_session(task)

        return Response(
            {
                "task_id": task.id,
                "conversation_id": conversation.id,
            },
            status=status.HTTP_201_CREATED,
        )


class AddDocumentToStoredPrintView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, task_id):

        task = get_object_or_404(
            Task,
            id=task_id,
            user=request.user,
        )

        # -----------------------------------------
        # Task validation
        # -----------------------------------------

        if task.task_type != Task.TaskType.STORED_PRINT:
            return Response(
                {
                    "error": (
                        "Documents can only be added "
                        "to stored print tasks."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if task.status != Task.Status.ACTIVE:
            return Response(
                {
                    "error": (
                        "This stored print task is no "
                        "longer active."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not task.storage_until:
            return Response(
                {
                    "error": (
                        "This task does not have "
                        "an active storage period."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if timezone.now() >= task.storage_until:
            return Response(
                {
                    "error": (
                        "The storage period for this task "
                        "has ended. Please create a new "
                        "stored print task."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------------
        # File
        # -----------------------------------------

        uploaded_file = request.FILES.get("file")

        if not uploaded_file:
            return Response(
                {
                    "error": "A file is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        extension = os.path.splitext(
            uploaded_file.name.lower()
        )[1]

        allowed_extensions = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
        }

        if extension not in allowed_extensions:
            return Response(
                {
                    "error": (
                        "Unsupported file type. "
                        "Allowed types are PDF, PNG, JPG "
                        "and JPEG."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------------
        # Copies
        # -----------------------------------------

        try:
            copies = int(
                request.data.get("copies", 1)
            )
        except (TypeError, ValueError):
            return Response(
                {
                    "error": "copies must be a valid number."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if copies < 1:
            return Response(
                {
                    "error": "Copies must be at least 1."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------------
        # Determine page count
        # -----------------------------------------

        if extension == ".pdf":

            try:
                reader = PdfReader(uploaded_file)
                page_count = len(reader.pages)
            except Exception:
                return Response(
                    {
                        "error": "Unable to read the PDF file."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            uploaded_file.seek(0)

        else:
            page_count = 1

        new_printed_pages = (
            page_count * copies
        )

        # -----------------------------------------
        # Existing printed pages
        # -----------------------------------------

        existing_pages = 0

        for document in task.documents.all():
            existing_pages += (
                document.page_count
                * document.copies
            )

        pending_pages = 0

        for document in task.pending_documents.all():
            pending_pages += (
                document.page_count
                * document.copies
            )

        total_pages = (
            existing_pages
            + pending_pages
            + new_printed_pages
        )

        if total_pages > 100:
            return Response(
                {
                    "error": (
                        "A stored print task can contain "
                        "at most 100 printed pages."
                    ),
                    "existing_pages": existing_pages,
                    "pending_pages": pending_pages,
                    "new_pages": new_printed_pages,
                    "total_pages": total_pages,
                    "maximum_pages": 100,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------------
        # Printing settings
        # -----------------------------------------

        print_settings = {
            "print_type": "stored",
            "orientation": request.data.get(
                "orientation",
                "portrait",
            ),
            "print_sides": request.data.get(
                "print_sides",
                "front_only",
            ),
        }

        # -----------------------------------------
        # Calculate printing price
        #
        # Keep this consistent with the existing
        # StartPrintTaskView:
        #
        # pages * copies × box.printing_price
        # -----------------------------------------

        printing_price = (
            task.box.printing_price
            or Decimal("0.00")
        )

        amount = (
            Decimal(page_count)
            * Decimal(copies)
            * printing_price
        )

        # -----------------------------------------
        # IMPORTANT:
        # No additional storage charge.
        # The existing storage period remains.
        # -----------------------------------------

        pending_document = (
            PendingPrintDocument.objects.create(
                task=task,
                file=uploaded_file,
                original_filename=uploaded_file.name,
                copies=copies,
                page_count=page_count,
                print_settings=print_settings,
                amount=amount,
            )
        )

        # -----------------------------------------
        # Create document-review conversation message
        # -----------------------------------------

        session = get_object_or_404(
            ConversationSession,
            task=task,
            task__user=request.user,
        )

        ConversationService.prepare_document_payment(
            session=session,
            pending_document=pending_document,
        )

        return Response(
            {
                "message": (
                    "Document uploaded successfully. "
                    "Payment is required to add it "
                    "to your stored print task."
                ),
                "task_id": task.id,
                "pending_document_id": pending_document.id,
                "filename": pending_document.original_filename,
                "page_count": page_count,
                "copies": copies,
                "total_printed_pages": new_printed_pages,
                "amount": str(amount),
                "storage_charge": "0.00",
                "storage_until": task.storage_until.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

class StartStorageTaskView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        box_id = request.data.get("box_id")
        drop_size = request.data.get("drop_size")
        duration = int(request.data.get("duration", 1))

        if not box_id:
            return Response(
                {"error": "Box is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        box = get_object_or_404(Box, id=box_id)

        cubby_map = {
            "small": Cubby.CubbyType.SMALL,
            "medium": Cubby.CubbyType.MEDIUM,
            "large": Cubby.CubbyType.LARGE,
        }

        #cubby = (
            #Cubby.objects
            #.filter(
                #box=box,
                #cubby_type=cubby_map[drop_size],
                #status=Cubby.Status.AVAILABLE,
            #)
            #.first()
        #)

        #if not cubby:
            #return Response(
                #{"error": "No available storage cubby."},
                #status=status.HTTP_400_BAD_REQUEST,
            #)

        #cubby.status = Cubby.Status.RESERVED
        #cubby.save()

        pricing = box.dropbox_pricing or {}

        hourly_rate = Decimal(
            str(pricing.get(drop_size, 0))
        )

        amount = hourly_rate * Decimal(duration)

        task = Task.objects.create(
            user=request.user,
            box=box,
            cubby=None,
            task_type=Task.TaskType.PACKAGE_STORAGE,
            amount=amount,
            storage_until=timezone.now() + timedelta(hours=duration),
            task_data={
                "size": drop_size,
                "storage_hours": duration,
            },
        )

        conversation = ConversationService.create_session(task)

        return Response(
            {
                "task_id": task.id,
                "conversation_id": conversation.id,
            },
            status=status.HTTP_201_CREATED,
        )


class PackageAccessRedeemView(APIView):
    permission_classes = []

    def get(self, request, token):
        try:
            data = ConversationService.redeem_package_access(
                token
            )
        except ValidationError as exc:
            detail = exc.message if hasattr(
                exc,
                "message",
            ) else str(exc)

            return Response(
                {
                    "detail": detail,
                },
                status=400,
            )

        return Response(data)


class CubbyConversationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50

class CubbyConversationHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cubby_id):
        conversations = (
            ConversationSession.objects
            .filter(
                cubby_id=cubby_id,
                task__user=request.user,
            )
            .select_related(
                "task",
                "task__box",
                "task__cubby",
            )
            .prefetch_related(
                "task__documents",
                Prefetch(
                    "messages",
                    queryset=ConversationMessage.objects.order_by(
                        "created_at",
                        "id",
                    ),
                ),
            )
            .annotate(
                last_activity_at=Max("messages__created_at")
            )
            .order_by(
                "-last_activity_at",
                "-started_at",
                "-id",
            )
        )

        paginator = CubbyConversationPagination()

        page = paginator.paginate_queryset(
            conversations,
            request,
            view=self,
        )

        results = []

        for index, conversation in enumerate(page):
            if index == 0:
                data = ConversationSerializer(
                    conversation,
                    context={"request": request},
                ).data
            else:
                data = ConversationSummarySerializer(
                    conversation,
                    context={"request": request},
                ).data

            results.append(data)

        return paginator.get_paginated_response(results)

class StationConversationListView(generics.ListAPIView):
    """
    Retrieves a paginated list of conversations for a specific printing station.
    """
    serializer_class = ConversationSerializer

    permission_classes = [IsAuthenticated] # Or whatever permissions you use

    def get_queryset(self):
        station_id = self.kwargs.get('station_id')
        user = self.request.user
        
        queryset = ConversationSession.objects.filter(
            task__station_id=station_id,
            user=user
        ).order_by('-created_at') # Order by newest first
        
        return queryset

class InstantPrintConversationHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conversations = (
            ConversationSession.objects
            .filter(
                task__user=request.user,
                task__task_type=Task.TaskType.INSTANT_PRINT,
            )
            .select_related(
                "task",
                "task__box",
                "task__cubby",
            )
            .prefetch_related(
                "task__documents",
                Prefetch(
                    "messages",
                    queryset=ConversationMessage.objects.order_by(
                        "created_at",
                        "id",
                    ),
                ),
            )
            .annotate(
                last_activity_at=Max("messages__created_at")
            )
            .order_by(
                "-last_activity_at",
                "-started_at",
                "-id",
            )
        )

        paginator = CubbyConversationPagination()

        page = paginator.paginate_queryset(
            conversations,
            request,
            view=self,
        )

        results = []

        for index, conversation in enumerate(page):
            if index == 0:
                data = ConversationSerializer(
                    conversation,
                    context={"request": request},
                ).data
            else:
                data = ConversationSummarySerializer(
                    conversation,
                    context={"request": request},
                ).data

            results.append(data)

        return paginator.get_paginated_response(results)

class ConversationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conversations = (
            ConversationSession.objects
            .filter(task__user=request.user)
            .select_related(
                "task",
                "task__box",
                "task__cubby",
            )
            .prefetch_related(
                "task__documents",
                Prefetch(
                    "messages",
                    queryset=ConversationMessage.objects.order_by(
                        "created_at",
                        "id",
                    ),
                ),
            )
            .annotate(
                last_activity_at=Max("messages__created_at"),
            )
            .order_by(
                "-last_activity_at",
                "-started_at",
                "-id",
            )
        )

        # -------------------------
        # Filters
        # -------------------------

        task_type = request.query_params.get("task_type")
        status = request.query_params.get("status")

        updated_after = request.query_params.get("updated_after")
        updated_before = request.query_params.get("updated_before")

        if task_type:
            conversations = conversations.filter(
                task__task_type=task_type
            )

        if status:
            conversations = conversations.filter(
                task__status=status
            )

        if updated_after:
            try:
                updated_after = datetime.fromisoformat(
                    updated_after.replace("Z", "+00:00")
                )
            except ValueError:
                return Response(
                    {
                        "error": (
                            "Invalid updated_after. "
                            "Use ISO 8601 format."
                        )
                    },
                    status=400,
                )

            conversations = conversations.filter(
                last_activity_at__gte=updated_after
            )

        if updated_before:
            try:
                updated_before = datetime.fromisoformat(
                    updated_before.replace("Z", "+00:00")
                )
            except ValueError:
                return Response(
                    {
                        "error": (
                            "Invalid updated_before. "
                            "Use ISO 8601 format."
                        )
                    },
                    status=400,
                )

            conversations = conversations.filter(
                last_activity_at__lte=updated_before
            )

        # -------------------------
        # Pagination
        # -------------------------

        paginator = ConversationPagination()

        page = paginator.paginate_queryset(
            conversations,
            request,
            view=self,
        )

        if page is None:
            serializer = ConversationSummarySerializer(
                conversations,
                many=True,
                context={"request": request},
            )

            return Response(serializer.data)

        # First conversation on the current page is expanded
        expand_id = page[0].id if page else None

        serializer = ConversationSummarySerializer(
            page,
            many=True,
            context={
                "request": request,
                "expand_conversation_id": expand_id,
                "hide_access_actions": True,
            },
        )

        return paginator.get_paginated_response(
            serializer.data
        )


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        session = get_object_or_404(
            ConversationSession.objects
            .select_related(
                "task",
                "task__box",
                "task__cubby",
            )
            .prefetch_related(
                "task__documents",
                Prefetch(
                    "messages",
                    queryset=ConversationMessage.objects.order_by(
                        "created_at",
                        "id",
                    ),
                ),
            ),
            id=session_id,
            task__user=request.user,
        )

        serializer = ConversationSerializer(session)

        return Response(serializer.data)


class ConversationActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(
            ConversationSession,
            id=session_id,
            task__user=request.user,
        )

        serializer = ConversationActionSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        updated_session = ConversationService.perform_action(
            session,
            serializer.validated_data['action'],
            request.data,
        )

        return Response(
            ConversationSerializer(updated_session).data
        )


class TaskBoxStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, task_id):
        task = get_object_or_404(
            Task.objects.select_for_update(),
            id=task_id,
        )

        box_status = request.data.get("box_status")

        valid_statuses = {
            Task.BoxStatus.QUEUED,
            Task.BoxStatus.RECEIVED,
            Task.BoxStatus.PROCESSING,
            Task.BoxStatus.PRINTING,
            Task.BoxStatus.WAITING_FOR_DEPOSIT,
            Task.BoxStatus.PACKAGE_STORED,
            Task.BoxStatus.COMPLETED,
            Task.BoxStatus.FAILED,
        }

        if box_status not in valid_statuses:
            return Response(
                {
                    "error": "Invalid box_status.",
                    "allowed": list(valid_statuses),
                },
                status=400,
            )

        task.box_status = box_status

        if box_status == Task.BoxStatus.COMPLETED:
            task.status = Task.Status.COMPLETED
            task.completed_at = timezone.now()

        if box_status == Task.BoxStatus.FAILED:
            task.status = Task.Status.FAILED

        task.save(
            update_fields=[
                "box_status",
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        ConversationService.add_box_status_message(
            task,
            box_status,
        )

        if box_status == Task.BoxStatus.COMPLETED:
            session = (
                ConversationSession.objects
                .filter(
                    task=task,
                    is_active=True,
                )
                .order_by("-id")
                .first()
            )

            if session:
                ConversationService._complete_conversation(
                    session
                )

        update_box_status_in_firestore(task)

        return Response({
            "task_id": task.id,
            "status": task.status,
            "box_status": task.box_status,
        })


# 1. View for the 4 Most Recent Dashboard Tasks
class DashboardRecentTasksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        time_threshold = now - timedelta(hours=48)

        # Fetch candidate tasks from the last 48 hours, ordered by newest first
        recent_tasks = (
            Task.objects
            .filter(
                user=request.user,
                created_at__gte=time_threshold
            )
            .select_related('box', 'cubby')
            .prefetch_related('documents', 'conversation')
            .order_by('-created_at')
        )

        # Because of the complex "Maximum of 1 instant_print" rule,
        # it is much more efficient to evaluate the final 4 in memory.
        final_tasks = []
        has_instant_print = False

        for task in recent_tasks:
            # Stop once we have our 4 tasks
            if len(final_tasks) >= 4:
                break

            # Rule 1: Handle instant_print (usually pending, but we'll accept active too). Max 1 allowed.
            if task.task_type == 'instant_print' and task.status in [Task.Status.PENDING, Task.Status.ACTIVE]:
                if not has_instant_print:
                    final_tasks.append(task)
                    has_instant_print = True
            
            # Rule 2: Other tasks MUST be active
            elif task.status == Task.Status.ACTIVE:
                final_tasks.append(task)

        serializer = RecentTaskSerializer(final_tasks, many=True)
        return Response(serializer.data)


# 2. View for All Tasks with Status Filtering
class AllTasksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get the status from query params (e.g., /api/tasks/?status=pending)
        status_param = request.query_params.get('status')
        now = timezone.now()

        # Base Query
        tasks = Task.objects.filter(user=request.user).select_related('box', 'cubby').prefetch_related('documents', 'conversation').order_by('-created_at')

        # Apply specific status filter if provided
        if status_param:
            tasks = tasks.filter(status=status_param)
        
        # Fallback to your original logic if no specific status is requested
        else:
            tasks = tasks.filter(
                Q(status__in=[
                    Task.Status.PENDING,
                    Task.Status.ACTIVE,
                ]) |
                Q(
                    status__in=[
                        Task.Status.COMPLETED,
                        Task.Status.WITHDRAWN,
                    ],
                    visible_until__gt=now,
                )
            )

        serializer = RecentTaskSerializer(tasks, many=True)
        return Response(serializer.data)



class TaskHistoryView(ListAPIView):
    serializer_class = TaskHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            Task.objects
            .filter(user=self.request.user)
            .filter(
                status__in=[
                    Task.Status.COMPLETED,
                    Task.Status.WITHDRAWN,
                    Task.Status.EXPIRED,
                    Task.Status.CANCELLED,
                ]
            )
            .select_related('box', 'cubby')
            .order_by('-completed_at', '-created_at')
        )

        task_type = self.request.query_params.get('task_type')
        status = self.request.query_params.get('status')

        if task_type:
            queryset = queryset.filter(task_type=task_type)

        if status:
            queryset = queryset.filter(status=status)

        return queryset


class TaskHistoryDetailView(RetrieveAPIView):
    serializer_class = TaskHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Task.objects.filter(user=self.request.user)


class WalletTransactionHistoryView(ListAPIView):
    serializer_class = WalletTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            WalletTransaction.objects
            .filter(wallet__user=self.request.user)
            .order_by('-created_at')
        )


class BoxClaimInstantPrintTaskView(APIView):
    """
    Allows an authenticated physical box to claim an instant-print
    task using the access code supplied to the customer after payment.
    """

    authentication_classes = []
    permission_classes = [IsAuthenticatedBox]

    def post(self, request):
        access_code = str(
            request.data.get("access_code", "")
        ).strip()

        if not access_code:
            return Response(
                {"error": "Access code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        box = request.box

        # The requesting box must be available and support printing.
        if not box.is_available:
            return Response(
                {"error": "This box is currently unavailable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not box.supports_printing:
            return Response(
                {"error": "This box does not support printing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():

            # Lock matching tasks to prevent simultaneous claims.
            matching_tasks = list(
                Task.objects
                .select_for_update()
                .filter(access_code=access_code)
                .order_by("id")[:2]
            )

            if not matching_tasks:
                return Response(
                    {"error": "Invalid access code."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Access codes are generated from a six-digit range.
            # Refuse ambiguous codes rather than claiming the wrong task.
            if len(matching_tasks) > 1:
                return Response(
                    {
                        "error": (
                            "This access code is associated with "
                            "multiple tasks. Please contact support."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            task = matching_tasks[0]

            if task.task_type != Task.TaskType.INSTANT_PRINT:
                return Response(
                    {"error": "This code is not for an instant-print task."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if task.status != Task.Status.ACTIVE:
                return Response(
                    {"error": "This print task is not active."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if task.box_status != Task.BoxStatus.QUEUED:
                return Response(
                    {"error": "This print task is not waiting to be claimed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if task.box_id is not None:
                return Response(
                    {
                        "error": "This task has already been claimed.",
                        "box": {
                            "id": task.box.id,
                            "name": task.box.name,
                        },
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # Assign the task to this physical box.
            task.box = box
            task.updated_at = timezone.now()

            task.save(
                update_fields=[
                    "box",
                    "updated_at",
                ]
            )

            # Add a message to the customer's conversation.
            session = (
                ConversationSession.objects
                .filter(task=task)
                .first()
            )

            if session:
                ConversationService._add_system_message(
                    session,
                    {
                        "title": "Print box assigned",
                        "message": (
                            f"Your print request has been assigned to "
                            f"{box.name}.\n\n"
                            f"Location: {box.address}\n\n"
                            "Your document is being prepared for printing."
                        ),
                        "box": {
                            "id": box.id,
                            "name": box.name,
                            "address": box.address,
                        },
                    },
                    message_type=ConversationMessage.MessageType.STATUS,
                )

            # Synchronize Firestore only after Django commits.
            transaction.on_commit(
                lambda: update_task_assignment_in_firestore(task)
            )

        return Response(
            {
                "message": "Instant print task successfully assigned.",
                "task_id": task.id,
                "box": {
                    "id": box.id,
                    "name": box.name,
                    "address": box.address,
                },
            },
            status=status.HTTP_200_OK,
        )

class BoxTaskDownloadView(APIView):
    """
    Endpoint for the physical box to securely download task details and files.
    """
    permission_classes = [IsAuthenticatedBox]

    def get(self, request, task_id):
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return Response(
                {"error": "Task not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # -------------------------------------------------
        # Security: Ensure this task belongs to this box
        # -------------------------------------------------
        if task.box_id != request.box.id:
            return Response(
                {"error": "This task is not assigned to this box."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # -------------------------------------------------
        # Serialize and return the data packet
        # -------------------------------------------------
        serializer = BoxTaskDownloadSerializer(task, context={'request': request})
        
        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

#//////////////////////////////////////////////////////////////////

    
@method_decorator(csrf_exempt, name='dispatch')
class InitializeDepositView(APIView):
    """Generates a Paystack checkout URL for the user to fund their wallet."""
    permission_classes = [IsAuthenticated]


    def post(self, request):
        conversation_id = request.data.get('conversation_id')
        try:
            amount_naira = float(request.data.get('amount'))
        except (TypeError, ValueError):
            return Response({"error": "Please provide a valid amount."}, status=status.HTTP_400_BAD_REQUEST)

        if amount_naira < 100:
            return Response({"error": "Minimum deposit is ₦100."}, status=status.HTTP_400_BAD_REQUEST)

        if not settings.PAYSTACK_SECRET_KEY:
            return Response({"error": "Payment gateway is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        deposit = Deposit.objects.create(user=request.user, amount=amount_naira)

        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "email": request.user.email,
            "amount": int(amount_naira * 100),
            "reference": deposit.reference,
            "callback_url": "http://localhost:5173/wallet/deposit/verify"
        }

        try:
            response = requests.post(url, json=data, headers=headers, timeout=10)
            response_data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            deposit.status = 'failed'
            deposit.save(update_fields=['status'])
            return Response({"error": f"Could not reach payment gateway: {str(e)}"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if response_data.get('status'):
            return Response({
                "authorization_url": response_data['data']['authorization_url'],
                "reference": deposit.reference
            }, status=status.HTTP_200_OK)
        else:
            deposit.status = 'failed'
            deposit.save(update_fields=['status'])
            return Response({"error": response_data.get('message', 'Could not connect to Paystack.')}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class VerifyDepositView(APIView):
    """Verifies the transaction with Paystack and credits the user's wallet."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reference = request.data.get('reference')

        if not reference:
            return Response(
                {"error": "Reference is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        deposit = get_object_or_404(
            Deposit,
            reference=reference,
            user=request.user
        )

        # If this deposit has already been successfully processed,
        # do not process or credit it again.
        if deposit.status == 'success':
            return Response(
                {
                    "message": "Wallet already credited.",
                    "new_balance": request.user.wallet.balance
                },
                status=status.HTTP_200_OK
            )

        # Ask Paystack to verify the transaction.
        url = f"https://api.paystack.co/transaction/verify/{reference}"

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
        }

        response = requests.get(
            url,
            headers=headers
        )

        response_data = response.json()

        # Payment was successful on Paystack.
        if (
            response_data.get('status')
            and response_data.get('data', {}).get('status') == 'success'
        ):
            with transaction.atomic():

                # Re-check the deposit status inside the transaction.
                deposit.refresh_from_db()

                if deposit.status == 'success':
                    return Response(
                        {
                            "message": "Wallet already credited.",
                            "new_balance": request.user.wallet.balance
                        },
                        status=status.HTTP_200_OK
                    )

                # Mark the deposit as successful.
                deposit.status = 'success'
                deposit.save(update_fields=['status'])

                # Credit the wallet.
                #
                # WalletService.deposit() is also idempotent,
                # so the same Paystack reference cannot credit
                # the wallet twice.
                wallet = WalletService.deposit(
                    user=request.user,
                    amount=deposit.amount,
                    reference=deposit.reference,
                    description='Paystack wallet deposit'
                )

            return Response(
                {
                    "message": "Deposit successful!",
                    "amount_deposited": deposit.amount,
                    "new_balance": wallet.balance
                },
                status=status.HTTP_200_OK
            )

        # Paystack did not confirm a successful payment.
        deposit.status = 'failed'
        deposit.save(update_fields=['status'])

        return Response(
            {
                "error": "Payment verification failed."
            },
            status=status.HTTP_400_BAD_REQUEST
        )


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    GET: Fetches the logged-in user's profile, wallet balance, and stats.
    PATCH: Allows the user to update their name or other editable fields.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # We override get_object so it ignores the URL and ALWAYS returns 
        # the currently authenticated user. This is a massive security best practice!
        return self.request.user


def calculate_haversine(lat1, lon1, lat2, lon2):
    """Calculates distance between two GPS coordinates in kilometers."""
    R = 6371.0 # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2)**2
    return R * 2 * math.asin(math.sqrt(a))





class BoxTaskStatusUpdateAPIView(APIView):
    """
    Development/testing endpoint.

    Simulates the physical OpenBox changing the status
    of a task and adds the status update to the user's
    conversation.
    """
    authentication_classes = []
    # This completely secures the endpoint. 
    # If the hardware doesn't have the token, Django rejects it with a 403 Forbidden automatically.
    permission_classes = [IsAuthenticatedBox]

    def post(self, request):
        # Optional security upgrade: 
        # Because we attached the box in permissions.py, you can now verify that 
        # the box making the request is actually the box assigned to this specific task!
        # current_box = request.box 
        
        task_id = request.data.get("task_id")
        box_status = request.data.get("box_status")

        if not task_id:
            return Response(
                {"error": "task_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not box_status:
            return Response(
                {"error": "box_status is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return Response(
                {"error": "Task not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ADD THIS SECURITY CHECK:
        # Ensure the box making the request is the box assigned to the task
        if task.box_id != request.box.id:
            return Response(
                {"error": "This task is not assigned to this box."},
                status=status.HTTP_403_FORBIDDEN,
            )

        valid_statuses = [
            choice[0]
            for choice in Task.BoxStatus.choices
        ]

        if box_status not in valid_statuses:
            return Response(
                {
                    "error": "Invalid box_status.",
                    "valid_statuses": valid_statuses,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -------------------------------------------------
        # Update task status
        # -------------------------------------------------

        task.box_status = box_status

        if box_status == Task.BoxStatus.COMPLETED:
            task.status = Task.Status.COMPLETED
            task.completed_at = timezone.now()

            task.save(
                update_fields=[
                    "box_status",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )

        else:
            task.save(
                update_fields=[
                    "box_status",
                    "updated_at",
                ]
            )

        # -------------------------------------------------
        # Add status update to conversation
        # -------------------------------------------------

        status_messages = {
            Task.BoxStatus.NOT_SENT: {
                "title": "Status pending",
                "message": (
                    "The task has been created but has not yet been "
                    "transmitted to the physical box."
                ),
            },

            Task.BoxStatus.QUEUED: {
                "title": "Print request queued",
                "message": (
                    "Your print request has been queued "
                    "and is waiting for the box to process it."
                ),
            },

            Task.BoxStatus.RECEIVED: {
                "title": "Print request received",
                "message": (
                    "The box has received your print request."
                ),
            },

            Task.BoxStatus.PROCESSING: {
                "title": "Preparing your print",
                "message": (
                    "Your document is now being prepared "
                    "for printing."
                ),
            },

            Task.BoxStatus.PRINTING: {
                "title": "Printing started",
                "message": (
                    "Your document is now being printed."
                ),
            },

            Task.BoxStatus.WAITING_FOR_DEPOSIT: {
                "title": "Ready for pickup",
                "message": (
                    "Your printed document is ready. "
                    "Please collect it from the box."
                ),
            },

            Task.BoxStatus.PACKAGE_STORED: {
                "title": "Package safely stored",
                "message": (
                    "Your package has been securely placed inside "
                    "the box cubby and is ready for pickup."
                ),
            },

            Task.BoxStatus.COMPLETED: {
                "title": "Task completed",
                "message": (
                    "Your request has been completed successfully."
                ),
            },

            Task.BoxStatus.FAILED: {
                "title": "Processing problem",
                "message": (
                    "The box was unable to complete your request. "
                    "Please contact support if you need assistance."
                ),
            },
        }

        message_content = status_messages.get(box_status)

        if message_content:

            session = (
                ConversationSession.objects
                .filter(task=task)
                .first()
            )

            if session:

                ConversationService._add_system_message(
                    session,
                    message_content,
                    message_type=(
                        ConversationMessage.MessageType.STATUS
                    ),
                )

                # Close the conversation only when the
                # physical box actually reports completion.
                if box_status == Task.BoxStatus.COMPLETED:
                    ConversationService._complete_conversation(
                        session
                    )

        # -------------------------------------------------
        # Update Firestore
        # -------------------------------------------------

        update_box_status_in_firestore(task)

        return Response(
            {
                "message": "Box status updated successfully.",
                "task_id": task.id,
                "status": task.status,
                "box_status": task.box_status,
            },
            status=status.HTTP_200_OK,
        )



class HardwareTestPrintView(APIView):
    # This disables authentication for this specific view
    permission_classes = [AllowAny] 
    # This tells Django to expect a file upload with form data
    parser_classes = (MultiPartParser, FormParser) 

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get('file')
        
        # Catch the new settings sent from the frontend 
        # (with safe defaults just in case they are missing)
        orientation = request.data.get('orientation', 'portrait')
        print_sides = request.data.get('print_sides', 'front_only')
        
        if not uploaded_file:
            return Response(
                {"error": "No file was received."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # ---------------------------------------------------------
        # HARDWARE TRIGGER GOES HERE
        # ---------------------------------------------------------
        print(f"🛠️ HARDWARE TEST: Received file '{uploaded_file.name}'")
        print(f"🛠️ HARDWARE TEST: Size: {uploaded_file.size} bytes")
        
        # Print the newly received settings
        print(f"🛠️ HARDWARE TEST: Orientation set to '{orientation}'")
        print(f"🛠️ HARDWARE TEST: Print mode set to '{print_sides}'")
        
        print("🛠️ HARDWARE TEST: Sending signal to physical printer...")
        
        return Response(
            {"message": "Print job started successfully!"}, 
            status=status.HTTP_200_OK
        )

def hardware_test_ui(request):
    return render(request, 'test_print.html')