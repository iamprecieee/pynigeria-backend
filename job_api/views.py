import uuid
import random
import hashlib

from django.contrib.auth.models import User
from django.db.models import Q
from django.db.transaction import atomic
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import (
    IsAdminUser,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from common.filterset import JobFilterset
from common.helper import Helper
from job_api.models import Job, JobSkill, Skill, Bookmark
from job_api.serializers import (
    JobSerializer,
    CreateBookmarkSerializer,
    BookmarkSerializer,
)

# Create your views here.


class JobViewset(viewsets.ModelViewSet, Helper):
    queryset = Job.objects.all().order_by("-created_at")
    serializer_class = JobSerializer
    # permission_classes = [IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["skills__name", "title", "company", "location"]
    ordering_fields = [
        "skills__name",
        "title",
        "company",
        "location",
        "posted_by__username",
    ]
    ordering = ["title"]
    filterset_class = JobFilterset
    lookup_field = "slug"

    def list(self, request, *args, **kwargs):
        raise MethodNotAllowed(method="get")

    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if (
            request.user.id == instance.posted_by.id
            or request.user.is_superuser
            or request.user.is_staff
        ):
            self.perform_destroy(instance)
            return Response(status=204)
        return Response(
            {"detail": "You do not have sufficient permission to perform this action"},
            status=400,
        )

    def get_permissions(self):
        if self.action == "create" or "destroy":
            permission_classes = [IsAuthenticated, IsAdminUser]
        else:
            permission_classes = [IsAuthenticatedOrReadOnly]
        return [permission() for permission in permission_classes]

    def filter_queryset(self, queryset):
        search_param = self.request.query_params.get("search")

        if search_param:
            search_terms = [
                term.strip().lower() for term in search_param.split(",") if term.strip()
            ]
            skill_filter = Q()
            for term in search_terms:
                skill_filter |= (
                    Q(skills__name__iexact=term)
                    | Q(title__icontains=term)
                    | Q(company__icontains=term)
                    | Q(location__icontains=term)
                )
            # Apply the filter to the queryset
            queryset = self.queryset.filter(skill_filter).distinct()

        # Return the filtered queryset
        return super().filter_queryset(queryset)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        modified_data = self.format_instance(serializer.data)
        return Response(modified_data)

    @atomic()
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data.get("title")
        company = serializer.validated_data.get("company")
        location = serializer.validated_data.get("location")
        description = serializer.validated_data.get("description")
        posted_by = self.request.user if self.request.user.is_authenticated else ""
        skills_data = serializer.validated_data.get("skills", [])
        input_value = [title, company, location, description, str(posted_by.id)]
        input_value.extend(data["name"].lower() for data in skills_data)
        random.shuffle(input_value)
        combined_input = " ".join(input_value).encode("utf-8")
        print(combined_input)
        seed = int(hashlib.sha256(combined_input).hexdigest(), 16)
        random.seed(seed)
        slug = uuid.UUID(int=random.getrandbits(128), version=4)

        try:

            job = Job(
                title=title.lower(),
                company=company.lower(),
                location=location.lower(),
                description=description.lower(),
                posted_by=posted_by,
                slug=slug,
            )
            job.save()

            for data in skills_data:
                skill_name = data["name"].strip().lower()
                skill, created = Skill.objects.get_or_create(name=skill_name)
                JobSkill.objects.create(job=job, skill=skill)

            job_serializer = self.get_serializer(job)

            return Response(job_serializer.data, status=201)
        except Exception as e:
            return Response(
                {"detail": "An unexpected error occures", "error": str(e)},
                status=500,
            )

    @action(
        methods=["get"],
        detail=False,
        url_path="job-list",
        url_name="job-list",
    )
    def jobs_list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            modified_response = self.format_list(serializer.data)
            return self.get_paginated_response(modified_response)

        serializer = self.get_serializer(queryset, many=True)
        modified_response = self.format_list(serializer.data)
        return Response(modified_response)


class BookmarkViewset(viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # User-specific bookmarks
        return Bookmark.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return CreateBookmarkSerializer
        return BookmarkSerializer

    def partial_update(self, request, *args, **kwargs):
        raise MethodNotAllowed(method="patch")

    def update(self, request, *args, **kwargs):
        raise MethodNotAllowed(method="put")

    @atomic()
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = serializer.validated_data.get("job")
        user = request.user
        bookmark = Bookmark(job=job, user=user)
        bookmark.save()
        return Response({"message": "Job bookmarked successfully"}, status=200)
