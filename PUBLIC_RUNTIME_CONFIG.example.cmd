@echo off
rem Public configuration reference only; launchers do not automatically load this file.
rem Copy the required set commands into the same Windows terminal before launching.
set "TASK_BACKEND=local"
rem Cloud mode requires the deployed us-west-2 AWS HTTPS base URL.
set "PUBLIC_TASK_BASE_URL="
rem Optional separate AWS task API base URL; blank uses PUBLIC_TASK_BASE_URL.
set "TASK_CLOUD_API_URL="
rem Cloud mode requires an explicit named AWS CLI profile. No key or session belongs here.
set "YOUBIKE_AWS_PROFILE="
rem YouBike task resources are fixed to this reviewed region.
set "YOUBIKE_AWS_REGION=us-west-2"
