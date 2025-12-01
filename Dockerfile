# Use the specific AWS Lambda Python base image
FROM public.ecr.aws/lambda/python:3.11

# Set working directory
WORKDIR /var/task

# Install system dependencies for PostgreSQL
RUN yum update -y && \
    yum install -y postgresql-devel gcc python3-devel && \
    yum clean all

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install -r requirements.txt --no-cache-dir

# Copy application code
COPY src/ .

# Set the CMD to your handler
CMD ["webhook_handler.lambda_handler"]