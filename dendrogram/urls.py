from django.urls import path

from . import views

urlpatterns = [
    path('profile/', views.ProfileList.as_view(), name="profile-list"),
    path('profile/<uuid:pk>/', views.ProfileDetail.as_view(), name="profile-detail"),
    path('dendrogram/', views.DendrogramList.as_view(), name="dendrogram-list"),
    path('dendrogram/<uuid:pk>/', views.DendrogramDetail.as_view(), name="dendrogram-detail"),
    path('plot/', views.Plotting.as_view(), name="plotting"),
]
