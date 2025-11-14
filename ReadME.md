Okay, here is a much more comprehensive and lengthy `README.md` file for the combined Notification Gateway and Template Service (with Mock User Service) project, incorporating the Swagger documentation setup, the architectural diagram, detailed explanations, troubleshooting, and the content from the provided file snippet.

```markdown
# Distributed Notification Platform (Gateway & Template Service)

This repository contains the core components of a distributed notification platform: the **Notification Gateway** and the **Template Service**. The Template Service also hosts a **Mock User Service** for local development and testing purposes, simulating the behavior of a separate User Management Service.

## Table of Contents

*   [Overview](#overview)
*   [Architecture](#architecture)
*   [Features](#features)
*   [Prerequisites](#prerequisites)
*   [Setup (Local Development)](#setup-local-development)
*   [API Endpoints (Notification Gateway)](#api-endpoints-notification-gateway)
*   [API Endpoints (Template Service - Including Mock User Service)](#api-endpoints-template-service---including-mock-user-service)
*   [Management Commands (Gateway)](#management-commands-gateway)
*   [Testing the Flow (Example)](#testing-the-flow-example)
*   [API Documentation (Swagger UI)](#api-documentation-swagger-ui)
*   [Troubleshooting](#troubleshooting)
*   [Deployment (Conceptual - e.g., Railway)](#deployment-conceptual---e.g.-railway)
*   [Best Practices](#best-practices)
*   [Contributing](#contributing)
*   [License](#license)

## Overview

This project demonstrates a scalable, multi-tenant notification system built with Django REST Framework (DRF). The primary goals are:

*   **API Gateway Functionality:** The Notification Gateway (`notification_gateway`) serves as the central, public-facing API endpoint. Clients authenticate using organization-specific API keys and submit notification requests.
*   **Service Integration:** The gateway communicates with downstream services (User, Template) to fetch recipient details and template content, ensuring data isolation per organization.
*   **Asynchronous Processing:** Notification sending is decoupled from the request/response cycle using RabbitMQ queues, allowing for high throughput and resilience.
*   **Caching & Optimization:** Redis is used for caching user/template data, rate limiting, and quota management, reducing latency and database load.
*   **Observability:** The system includes comprehensive logging with correlation IDs, Prometheus metrics for monitoring, and health check endpoints.
*   **Template Management:** The Template Service (`template_man`) provides a robust API for creating, versioning, publishing, and managing notification templates (Email, Push, SMS).
*   **User Management (Mocked):** A mock User Service endpoint is included within the Template Service project to simplify local testing without requiring a separate, full-featured user service.

The system is designed to be deployed as separate microservices in a production environment, but this repository provides a local setup combining them.

## Architecture

```mermaid
graph TB
    subgraph "Client Application"
        A["Client App (e.g., Frontend, Backend Service)"]
    end

    subgraph "Notification Platform"
        subgraph "Notification Gateway (Gateway Service)"
            B["NotificationAPIView (POST /api/v1/notifications/)"]
            C["Authentication (APIKeyAuth)"]
            D["User Lookup (UserService API)"]
            E["Template Fetch (TemplateService API)"]
            F["Validation & Quota Check"]
            G["Create Notification Record (DB)"]
            H["Publish to Queue (RabbitMQ)"]
            I["HealthCheckView (GET /health/)"]
            J["Documentation (Swagger UI)"]
            K["NotificationStatusCheckView (POST /api/v1/notifications/status/)"]
        end

        subgraph "Template Service (Template Service)"
            L["TemplateAPIView (GET/POST/PUT/PATCH /api/v1/templates/)"]
            M["Template Model (DB)"]
            N["Template Cache (Redis)"]
            O["InternalOrganizationSyncView (POST /mock/organizations/)"] # Internal endpoint for org sync from gateway
            P["HealthCheckView (GET /health/)"]
            Q["Documentation (Swagger UI)"]
        end

        subgraph "User Service (Mocked by Template Service for this setup)"
            R["UserServiceView (GET/POST/PATCH /api/v1/users/)"]
            S["User Model (DB - in Template Service's DB for mock)"]
            T["User Cache (Redis - in Template Service's Redis for mock)"]
        end

        subgraph "Message Queue & Workers"
            U["RabbitMQ (Queues: email.queue, push.queue)"]
            V["Email Worker (Consumes email.queue)"]
            W["Push Worker (Consumes push.queue)"]
        end

        subgraph "Data Stores"
            X["Gateway DB (SQLite/PostgreSQL - Organizations, Notifications)"]
            Y["Template Service DB (SQLite/PostgreSQL - Templates, Organizations, Users for mock)"]
            Z["Redis (Caching, Rate Limiting, Quota Tracking)"]
        end
    end

    A -->|X-API-Key, JSON Payload| B
    B --> C
    C -->|Success| D
    C -->|Failure| B
    D -->|X-Organization-ID| R
    R -->|User Data| D
    D -->|Success| E
    D -->|Failure| B
    E -->|X-Organization-ID| L
    L -->|Template Data| E
    E -->|Success| F
    E -->|Failure| B
    F -->|Validation/Quota Fail| B
    F -->|Success| G
    G --> H
    H --> U
    V --> U
    W --> U
    V -->|Deliver Email| S[User's Email]
    W -->|Deliver Push| S[User's Device]

    X <--> G
    Y <--> R
    Y <--> L
    Z <--> D
    Z <--> E
    Z <--> F
    Z <--> H

    I -->|Health Check| X
    I -->|Health Check| Z
    I -->|Health Check| U
    I -->|Health Check| D
    I -->|Health Check| E
    J -->|Swagger UI| B
    K -->|Check Status| X
    O -->|Sync Org Data| M
    P -->|Health Check| Y
    P -->|Health Check| Z
    Q -->|Swagger UI| L

    style A fill:#cde4ff
    style B fill:#f9f,stroke:#333,stroke-width:2px
    style L fill:#f9f,stroke:#333,stroke-width:2px
    style R fill:#f9f,stroke:#333,stroke-width:2px
    style U fill:#ffe4b5
    style X fill:#e0ffe0
    style Y fill:#e0ffe0
    style Z fill:#fffacd
    style V fill:#ffccdd
    style W fill:#ffccdd
```

### Components Explained:

*   **Client Application:** Initiates the notification request by calling the Gateway's API.
*   **Notification Gateway:**
    *   **API Endpoint:** `NotificationAPIView` handles incoming requests.
    *   **Authentication:** `APIKeyAuthentication` validates the `X-API-Key` header.
    *   **Authorization:** Ensures the requesting organization has access to the specified user/template by passing the organization ID (`X-Organization-ID`) in requests to downstream services.
    *   **Caching:** `redis_client` is used for caching user/template data and enforcing rate limits/quota.
    *   **Service Communication:** Makes HTTP calls to the User and Template services using `requests` or `httpx`.
    *   **Database:** Stores `Organization` and `Notification` records.
    *   **Message Queue:** Uses `pika` (or `aio-pika` if async) to publish messages to RabbitMQ.
    *   **Other Views:** `HealthCheckView`, `NotificationStatusCheckView`, `InternalOrganizationSyncView` (for syncing orgs to user/template services), `UserServiceView` (mock user service proxy).
*   **Template Service:**
    *   **API Endpoint:** `TemplateAPIView` handles template CRUD operations.
    *   **Authentication:** `InternalAPIAuthentication` (or potentially public endpoints for gateway) validates internal secrets or scopes requests based on `X-Organization-ID`.
    *   **Authorization:** Filters templates based on the `X-Organization-ID` header.
    *   **Caching:** `redis_client` caches template data.
    *   **Database:** Stores `Template`, `Organization` (for scoping templates), and potentially `User` records (for the mock service).
    *   **Other Views:** `HealthCheckView`, `InternalOrganizationSyncView` (receives sync requests from gateway).
*   **Mock User Service (within Template Service):**
    *   **API Endpoint:** `UserServiceView` handles user CRUD operations (for local testing).
    *   **Authentication:** May use `InternalAPIAuthentication` for internal calls or be public if secured by the gateway.
    *   **Authorization:** Filters users based on the `X-Organization-ID` header.
    *   **Storage:** Uses an in-memory dictionary (`self.users_db`) or a database model within the template service's database.
*   **RabbitMQ:** Acts as the message broker, decoupling the gateway from the actual delivery workers.
*   **Workers:** Consume messages from queues and perform the actual sending (e.g., SMTP for email, FCM for push).
*   **Redis:** Provides caching, rate limiting, and quota management across services.
*   **Database (Gateway):** Stores organization details and notification records.
*   **Database (Template Service):** Stores templates, organizations (for scoping), and potentially mock user data.

## Features

*   **Multi-Tenant API Gateway:** Secure API using organization-specific API keys (`X-API-Key` header). Requests are scoped to the organization identified by the key.
*   **Per-Organization Scoping:** User and template lookups are confined to the organization associated with the authenticated API key via the `X-Organization-ID` header passed between services.
*   **User Lookup (via Mock User Service):** Fetches user data (email, preferences, push token) from the mock user service endpoint (hosted by the template service).
*   **Template Fetching (via Template Service):** Retrieves template content (subject, body) from the template service.
*   **Variable Validation:** Ensures all required variables for a template are provided in the notification request.
*   **Asynchronous Processing:** Accepts requests and queues them using RabbitMQ for decoupled, scalable delivery.
*   **Rate Limiting:** Limits the number of requests per minute per organization using Redis.
*   **Quota Management:** Tracks and enforces notification quotas per organization using Redis (two-phase commit pattern).
*   **Caching:** Caches user and template data fetched from services using Redis to improve performance.
*   **Idempotency:** Prevents duplicate processing of the same notification request using the `request_id` field and Redis.
*   **Observability:** Comprehensive logging with correlation IDs, Prometheus metrics for monitoring, and health check endpoints.
*   **Template Management API:** Comprehensive API for creating, updating, versioning, and publishing templates, scoped to organizations.
*   **Mock User Service API:** Provides endpoints for managing users (create, get, update, preferences) scoped to organizations, primarily for local development.
*   **API Documentation:** Interactive API documentation available via Swagger UI generated using `drf-spectacular`.

## Prerequisites

*   **Python 3.11+**
*   **Virtual Environment Tool** (e.g., `venv`)
*   **Redis Server** (e.g., `redis-server`)
*   **RabbitMQ Server** (e.g., `rabbitmq-server`)
*   **PostgreSQL Server** (if using production settings) or **SQLite** (for development)
*   **System Dependencies:** On Linux/macOS, you might need `build-essential`, `libpq-dev`, `python3-dev` (or equivalent on your distro) for installing `psycopg2-binary` or other compiled packages. On Windows, ensure Visual Studio Build Tools or similar are available if compiling packages from source is required (though `psycopg2-binary` often avoids this).

## Setup (Local Development)

1.  **Clone the Repository:**
    ```bash
    git clone <your_repository_url>
    cd notification_gateway # Navigate to the gateway project directory first
    ```

2.  **Create and Activate Virtual Environment for Gateway:**
    ```bash
    python -m venv venv_gateway
    source venv_gateway/bin/activate # On Linux/macOS
    # On Windows: venv_gateway\Scripts\activate
    ```

3.  **Install Gateway Dependencies:**
    ```bash
    pip install -r requirements.txt
    # Ensure drf-spectacular is installed
    # pip install drf-spectacular # Run if not in requirements.txt
    ```

4.  **Configure Gateway Environment Variables:**
    Create a `.env` file in the `notification_gateway` directory (`notification_gateway/.env`).
    ```env
    # notification_gateway/.env
    SECRET_KEY=your_strong_secret_key_for_gateway_here_123!@#
    INTERNAL_API_SECRET=7175326e-9606-4fae-abe3-bc2ac6e55ea0 # Shared secret for internal communication
    # Database (Example using SQLite for dev)
    DB_ENGINE=django.db.backends.sqlite3
    DB_NAME=db.sqlite3
    # DB_HOST=localhost # Not needed for SQLite
    # DB_PORT=5432       # Not needed for SQLite
    # DB_USER=postgres   # Not needed for SQLite
    # DB_PASSWORD=postgres # Not needed for SQLite
    # RabbitMQ (Example using default guest/guest credentials on localhost)
    RABBITMQ_URL=amqp://guest:guest@localhost:5672
    # Service URLs (Pointing to the template service which hosts the mock user service)
    USER_SERVICE_URL=http://127.0.0.1:8002 # Points to the template service which handles mock user endpoints
    TEMPLATE_SERVICE_URL=http://127.0.0.1:8002 # Points to the template service itself
    # Redis
    REDIS_URL=redis://localhost:6379/1
    # Debug Mode
    DEBUG=True
    ALLOWED_HOSTS=localhost,127.0.0.1
    AND MORE CHECK .ENV EXAMPLE
    ```

5.  **Run Gateway Migrations:**
    ```bash
    python manage.py migrate
    ```

6.  **Navigate to Template Service Directory:**
    ```bash
    cd ../template_man # Go up one level and into template_man
    # Activate the venv for the template service (create one if needed)
    # python -m venv venv_template
    source venv_template/bin/activate # Activate the venv for template_man
    ```

7.  **Install Template Service Dependencies:**
    ```bash
    pip install -r requirements.txt
    # Ensure drf-spectacular is installed in this venv too
    # pip install drf-spectacular # Run if not in requirements.txt
    ```

8.  **Configure Template Service Environment Variables:**
    Create a `.env` file in the `template_man` directory (`template_man/.env`).
    ```env
    # template_man/.env
    SECRET_KEY=your_strong_secret_key_for_template_service_here_456!@#
    INTERNAL_API_SECRET=7175326e-9606-4fae-abe3-bc2ac6e55ea0 # Must match the gateway's secret
    # Database (Example using SQLite for dev)
    DB_ENGINE=django.db.backends.sqlite3
    DB_NAME=db.sqlite3
    # DB_HOST=localhost # Not needed for SQLite
    # DB_PORT=5432       # Not needed for SQLite
    # DB_USER=postgres   # Not needed for SQLite
    # DB_PASSWORD=postgres # Not needed for SQLite
    # Redis
    REDIS_URL=redis://localhost:6379/2 # Use a different DB number for isolation if needed
    # Debug Mode
    DEBUG=True
    ALLOWED_HOSTS=localhost,127.0.0.1
    ```

9.  **Run Template Service Migrations:**
    ```bash
    python manage.py migrate
    ```

10. **Start the Template Service Server (hosts Mock User Service):**
    ```bash
    python manage.py runserver 8002
    ```
 CHECK TEMPLATES SERVICE DOC FOR MORE

11. **In a New Terminal, Navigate Back to Gateway Directory:**
    ```bash
    cd /path/to/notification_gateway # Replace with your actual path
    source venv_gateway/bin/activate # Activate the gateway's venv
    ```

12. **Start the Notification Gateway Server:**
    ```bash
   
    ```

## API Endpoints (Notification Gateway)

### 1. Create Notification

*   **Endpoint:** `POST /api/v1/notifications/`
*   **Description:** Submits a new notification request for processing.
*   **Authentication:** Requires a valid `X-API-Key` header associated with an active organization.
*   **Headers:**
    *   `X-API-Key: <your_org_api_key>` (Required)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (JSON):**
    ```json
    {
      "notification_type": "email|push|sms", // (Required) Type of notification to send
      "user_id": "string",               // (Required) Unique ID of the recipient user
      "template_code": "string",         // (Required) Unique code identifying the template to use
      "variables": {                     // (Required) Variables to fill the template placeholders
        "name": "John Doe",
        "link": "https://example.com/activate"
      },
      "request_id": "string",            // (Optional) Unique ID for this request (for idempotency). Auto-generated if omitted.
      "priority": integer,               // (Optional) Priority level for processing (default: 5)
      "metadata": {                      // (Optional) Additional metadata associated with the notification
        "source": "signup_flow"
      }
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/notifications/ -H "Content-Type: application/json" -H "X-API-Key: org_your_valid_api_key_here" -d "{\"notification_type\": \"email\", \"user_id\": \"user_abc123...\", \"template_code\": \"welcome_email\", \"variables\": {\"name\": \"John Doe\", \"link\": \"https://example.com/activate\"}, \"request_id\": \"req_unique_id_for_this_request\", \"priority\": 7, \"metadata\": {\"source\": \"manual_test\"}}"
    ```
*   **Response (Success):**
    *   **Status:** `202 Accepted`
    *   **Body:**
        ```json
        {
          "success": true,
          "data": {
            "notification_id": "notif_xyz789...",
            "status": "accepted",
            "request_id": "req_unique_id_for_this_request",
            "correlation_id": "corr_abc123..."
          },
          "message": "Notification accepted for processing",
          "meta": {
            "total": 1,
            "limit": 1,
            "page": 1,
            "total_pages": 1,
            "has_next": false,
            "has_previous": false
          }
        }
        ```
*   **Response (Error):**
    *   **Status:** `4xx` or `5xx` (e.g., 400, 401, 404, 429, 500)
    *   **Body:**
        ```json
        {
          "success": false,
          "error": "string", // e.g., "missing_fields", "authentication_required", "user_not_found", "template_not_found", "rate_limit_exceeded", "internal_error"
          "message": "string", // Human-readable description of the error
          "meta": { ... } // Standard meta information
        }
        ```

### 2. Check Notification Status

*   **Endpoint:** `POST /api/v1/notifications/status/`
*   **Description:** Retrieves the status of a previously submitted notification.
*   **Authentication:** Requires a valid `X-API-Key` header associated with the organization that created the notification.
*   **Headers:**
    *   `X-API-Key: <your_org_api_key>` (Required)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (JSON):**
    ```json
    {
      "notification_id": "string" // (Required) The ID of the notification to check
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/notifications/status/ -H "Content-Type: application/json" -H "X-API-Key: org_your_valid_api_key_here" -d "{\"notification_id\": \"notif_xyz789...\"}"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:**
        ```json
        {
          "success": true,
          "data": {
            "notification_id": "notif_xyz789...",
            "status": "queued|processing|delivered|failed|bounced|rejected", // Current status
            "notification_type": "email|push|sms",
            "template_code": "welcome_email",
            "created_at": "2023-10-27T10:00:00.000000Z",
            "updated_at": "2023-10-27T10:01:00.000000Z",
            "delivered_at": "2023-10-27T10:01:30.000000Z", // Present if delivered
            "error_message": "string" // Present if status is 'failed' or 'rejected'
          },
          "message": "Notification status retrieved",
          "meta": { ... } // Standard meta information
        }
        ```
*   **Response (Error):**
    *   **Status:** `4xx` or `5xx` (e.g., 400, 401, 404)
    *   **Body:** Similar to the Create Notification error response.

### 3. Health Check

*   **Endpoint:** `GET /health/`
*   **Description:** Provides a health status check for the gateway and its dependencies (Database, Redis, RabbitMQ, User Service, Template Service, Email service).
*   **Authentication:** None required.
*   **Headers:** None required.
*   **Request Body:** None.
*   **Example Request (One Line):**
    ```bash
    curl -X GET http://127.0.0.1:8000/health/
    ```
*   **Response:**
    *   **Status:** `200 OK` if healthy, `503 Service Unavailable` if unhealthy.
    *   **Body:** JSON object containing status, timestamp, service name, version, and dependency checks.

## API Endpoints (Template Service - Including Mock User Service)

These endpoints are accessed via the gateway's URLs because the `USER_SERVICE_URL` and `TEMPLATE_SERVICE_URL` settings point to the template service's host/port. The gateway acts as a proxy for user requests and calls the template service directly for template requests.

### 1. Create User (Mock User Service via Gateway Port 8000)

*   **Endpoint:** `POST /api/v1/users/` (Accessed via Gateway)
*   **Description:** Creates a new user in the mock user service's storage (in-memory or DB).
*   **Authentication:** Requires `X-API-Key` header (authenticated by the gateway).
*   **Authorization:** Requires `X-Organization-ID` header to specify which organization the user belongs to.
*   **Headers (via Gateway):**
    *   `X-API-Key: <org_api_key_from_gateway>` (Required, validated by gateway)
    *   `X-Organization-ID: <org_id>` (Required, passed by gateway to mock service)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (via Gateway):**
    ```json
    {
      "email": "string",           // (Required) User's email address
      "name": "string",            // (Required) User's full name
      "password": "string",        // (Required) User's password (stored as plain text in mock)
      "push_token": "string",      // (Optional) Push notification token
      "preferences": {             // (Optional) Notification preferences
        "email": true,
        "push": false
      }
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/users/ -H "Content-Type: application/json" -H "X-API-Key: org_YourValidAPIKeyFromCreateOrgCommand" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand" -d "{\"email\": \"mock_user@example.com\", \"name\": \"Mock Test User\", \"password\": \"securepassword123\", \"push_token\": \"token_mock_user\", \"preferences\": {\"email\": true, \"push\": false}}"
    ```
*   **Response (Success):**
    *   **Status:** `201 Created`
    *   **Body:** JSON object containing the created user data (excluding password).
*   **Response (Error):**
    *   **Status:** `400 Bad Request`, `409 Conflict`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 2. Get User by ID (Mock User Service via Gateway Port 8000)

*   **Endpoint:** `GET /api/v1/users/<user_id>/` (Accessed via Gateway)
*   **Description:** Retrieves a user's details.
*   **Authentication:** Requires `X-API-Key` header (via gateway).
*   **Authorization:** Requires `X-Organization-ID` header. The user must belong to the specified organization.
*   **Headers (via Gateway):**
    *   `X-API-Key: <org_api_key_from_gateway>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
*   **Request Body:** None.
*   **Example Request (One Line):**
    ```bash
    curl -X GET http://127.0.0.1:8000/api/v1/users/THE_USER_ID_FROM_CREATE_RESPONSE/ -H "X-API-Key: org_YourValidAPIKeyFromCreateOrgCommand" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:** JSON object containing the user data.
*   **Response (Error):**
    *   **Status:** `404 Not Found`, `403 Forbidden`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 3. Get User Preferences (Mock User Service via Gateway Port 8000)

*   **Endpoint:** `GET /api/v1/users/<user_id>/preferences/` (Accessed via Gateway)
*   **Description:** Retrieves a user's notification preferences.
*   **Authentication:** Requires `X-API-Key` header (via gateway).
*   **Authorization:** Requires `X-Organization-ID` header. The user must belong to the specified organization.
*   **Headers (via Gateway):**
    *   `X-API-Key: <org_api_key_from_gateway>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
*   **Request Body:** None.
*   **Example Request (One Line):**
    ```bash
    curl -X GET http://127.0.0.1:8000/api/v1/users/THE_USER_ID_FROM_CREATE_RESPONSE/preferences/ -H "X-API-Key: org_YourValidAPIKeyFromCreateOrgCommand" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:** JSON object containing the user's preferences.
*   **Response (Error):**
    *   **Status:** `404 Not Found`, `403 Forbidden`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 4. Update User Details (Mock User Service via Gateway Port 8000)

*   **Endpoint:** `PATCH /api/v1/users/<user_id>/` (Accessed via Gateway)
*   **Description:** Updates a user's profile details (name, email, push_token).
*   **Authentication:** Requires `X-API-Key` header (via gateway).
*   **Authorization:** Requires `X-Organization-ID` header. The user must belong to the specified organization.
*   **Headers (via Gateway):**
    *   `X-API-Key: <org_api_key_from_gateway>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (via Gateway):**
    ```json
    {
      "name": "string",            // (Optional) New name
      "email": "string",           // (Optional) New email
      "push_token": "string"       // (Optional) New push token
      // Note: Updating password might require a different endpoint or logic
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X PATCH http://127.0.0.1:8000/api/v1/users/THE_USER_ID_FROM_CREATE_RESPONSE/ -H "Content-Type: application/json" -H "X-API-Key: org_YourValidAPIKeyFromCreateOrgCommand" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand" -d "{\"name\": \"Updated Mock User Name\", \"push_token\": \"token_updated_mock_user\"}"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:** JSON object containing the updated user data.
*   **Response (Error):**
    *   **Status:** `400 Bad Request`, `404 Not Found`, `403 Forbidden`, `409 Conflict`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 5. Update User Preferences (Mock User Service via Gateway Port 8000)

*   **Endpoint:** `PATCH /api/v1/users/<user_id>/preferences/` (Accessed via Gateway)
*   **Description:** Updates a user's notification preferences.
*   **Authentication:** Requires `X-API-Key` header (via gateway).
*   **Authorization:** Requires `X-Organization-ID` header. The user must belong to the specified organization.
*   **Headers (via Gateway):**
    *   `X-API-Key: <org_api_key_from_gateway>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (via Gateway):**
    ```json
    {
      "preferences": {             // (Required) Updated preferences object
        "email": false,
        "push": true
      }
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X PATCH http://127.0.0.1:8000/api/v1/users/THE_USER_ID_FROM_CREATE_RESPONSE/preferences/ -H "Content-Type: application/json" -H "X-API-Key: org_YourValidAPIKeyFromCreateOrgCommand" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand" -d "{\"preferences\": {\"email\": false, \"push\": true}}"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:** JSON object confirming the updated preferences.
*   **Response (Error):**
    *   **Status:** `400 Bad Request`, `404 Not Found`, `403 Forbidden`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 6. Create Template (Template Service Port 8002 - Direct Access)

*   **Endpoint:** `POST /api/v1/templates/` (Accessed directly on Template Service)
*   **Description:** Creates a new template scoped to an organization.
*   **Authentication:** Requires `X-Internal-Secret` header (authenticated by the template service).
*   **Authorization:** Requires `X-Organization-ID` header to specify which organization the template belongs to.
*   **Headers (Direct to Template Service):**
    *   `X-Internal-Secret: <internal_secret>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
    *   `Content-Type: application/json` (Required for JSON body)
*   **Request Body (Direct to Template Service):**
    ```json
    {
      "code": "string",              // (Required) Unique template code
      "name": "string",              // (Required) Template name
      "description": "string",       // (Optional) Description
      "type": "email|push|sms",      // (Required) Template type
      "subject": "string",           // (Optional for push/sms, required for email) Email subject line
      "content": "string",           // (Required) Template content with {{variables}}
      "html_content": "string",      // (Optional) HTML version for email templates
      "language": "en",              // (Optional) Language code (default: en)
      "status": "draft|active",      // (Optional) Initial status (default: draft)
      "variables": ["string"],       // (Optional) Required variables
      "optional_variables": ["string"] // (Optional) Optional variables
    }
    ```
*   **Example Request (One Line):**
    ```bash
    curl -X POST http://127.0.0.1:8002/api/v1/templates/ -H "Content-Type: application/json" -H "X-Internal-Secret: 7175326e-9606-4fae-abe3-bc2ac6e55ea0" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand" -d "{\"code\": \"welcome_email_direct\", \"name\": \"Welcome Email Direct\", \"description\": \"Welcome template created directly on template service\", \"type\": \"email\", \"subject\": \"Welcome, {{ name }}!\", \"content\": \"Hi {{ name }},\\n\\nThanks for joining!\\n\\nBest regards,\\nThe Team\", \"html_content\": \"<html><body><p>Hi {{ name }},</p><p>Thanks for joining!</p><p>Best regards,<br>The Team</p></body></html>\", \"language\": \"en\", \"status\": \"active\", \"variables\": [\"name\"], \"optional_variables\": []}"
    ```
*   **Response (Success):**
    *   **Status:** `201 Created`
    *   **Body:** JSON object containing the created template data.
*   **Response (Error):**
    *   **Status:** `400 Bad Request`, `409 Conflict`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 7. Get Template by Code (Template Service Port 8002 - Direct Access)

*   **Endpoint:** `GET /api/v1/templates/<code>/` (Accessed directly on Template Service)
*   **Description:** Retrieves a specific template by its code, scoped to an organization.
*   **Authentication:** Requires `X-Internal-Secret` header (authenticated by the template service).
*   **Authorization:** Requires `X-Organization-ID` header. The template must belong to the specified organization.
*   **Headers (Direct to Template Service):**
    *   `X-Internal-Secret: <internal_secret>` (Required)
    *   `X-Organization-ID: <org_id>` (Required)
*   **Request Body:** None.
*   **Example Request (One Line):**
    ```bash
    curl -X GET http://127.0.0.1:8002/api/v1/templates/welcome_email_direct/ -H "X-Internal-Secret: 7175326e-9606-4fae-abe3-bc2ac6e55ea0" -H "X-Organization-ID: org_YourValidOrgIDFromCreateOrgCommand"
    ```
*   **Response (Success):**
    *   **Status:** `200 OK`
    *   **Body:** JSON object containing the template data.
*   **Response (Error):**
    *   **Status:** `404 Not Found`, `403 Forbidden`, `500 Internal Server Error`
    *   **Body:** JSON object describing the error.

### 8. Health Check (Template Service)

*   **Endpoint:** `GET /health/` (on Template Service Port 8002)
*   **Description:** Provides a health status check for the template service and its dependencies (Database, Redis).
*   **Authentication:** None required.
*   **Headers:** None required.
*   **Request Body:** None.
*   **Example Request (One Line):**
    ```bash
    curl -X GET http://127.0.0.1:8002/health/
    ```
*   **Response:**
    *   **Status:** `200 OK` if healthy, `503 Service Unavailable` if unhealthy.
    *   **Body:** JSON object containing status, timestamp, service name, version, and dependency checks.

## Management Commands (Gateway)

### Create Organization

Creates an organization in the gateway's database and syncs it to the user service (mocked by the template service) and the template service itself via internal endpoints.

```bash
python manage.py create_org "OrganizationName" --plan pro --quota 10000
```

*   `--skip-user-service`: Skips syncing to the user service (if configured separately).
*   `--skip-template-service`: Skips syncing to the template service (if configured separately).

## Testing the Flow (Example)

1.  **Create an Organization:**
    *   Run the management command in the `notification_gateway` directory.
    *   Note the **Organization ID** and **API Key**.
    ```bash
    python manage.py create_org "TestOrgFinalComprehensive" --plan pro --quota 50000
    ```

2.  **Create a User (via Mock User Service on Gateway Port 8000):**
    *   Use the Organization ID from step 1.
    *   Use the API Key from step 1 for authentication with the gateway.
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/users/ -H "Content-Type: application/json" -H "X-API-Key: org_TheAPIKeyFromStep1" -H "X-Organization-ID: org_id_from_step_1" -d "{\"email\": \"fresh_test_user@example.com\", \"name\": \"Fresh Test User\", \"password\": \"securepassword123\", \"push_token\": \"token_fresh_test\", \"preferences\": {\"email\": true, \"push\": false}}"
    ```
    *   Note the **User ID** from the response.

3.  **Create a Template (on Template Service directly via Port 8002):**
    *   Use the Internal API Secret configured for the template service and the Organization ID from step 1.
    ```bash
    curl -X POST http://127.0.0.1:8002/api/v1/templates/ -H "Content-Type: application/json" -H "X-Internal-Secret: 7175326e-9606-4fae-abe3-bc2ac6e55ea0" -H "X-Organization-ID: org_id_from_step_1" -d "{\"code\": \"welcome_email_comp\", \"name\": \"Welcome Email Comprehensive\", \"description\": \"Welcome template for users in TestOrgFinalComprehensive\", \"type\": \"email\", \"subject\": \"Welcome, {{ name }}!\", \"content\": \"Hi {{ name }},\\n\\nThanks for joining TestOrgFinalComprehensive!\\n\\nBest regards,\\nThe Team\", \"html_content\": \"<html><body><p>Hi {{ name }},</p><p>Thanks for joining <strong>TestOrgFinalComprehensive</strong>!</p><p>Best regards,<br>The Team</p></body></html>\", \"language\": \"en\", \"status\": \"active\", \"variables\": [\"name\"], \"optional_variables\": []}"
    ```

4.  **Send a Notification (via Gateway API on Port 8000):**
    *   Use the API Key from step 1, the User ID from step 2, and the Template Code from step 3.
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/notifications/ -H "Content-Type: application/json" -H "X-API-Key: org_TheAPIKeyFromStep1" -d "{\"notification_type\": \"email\", \"user_id\": \"user_id_from_step_2\", \"template_code\": \"welcome_email_comp\", \"variables\": {\"name\": \"Comprehensive Test Recipient\"}, \"request_id\": \"req_test_comp_flow_manual_step4\", \"priority\": 7}"
    ```

5.  **Check Notification Status (via Gateway API on Port 8000):**
    *   Use the API Key and the notification ID returned from step 4 (or check the DB/logs).
    ```bash
    curl -X POST http://127.0.0.1:8000/api/v1/notifications/status/ -H "Content-Type: application/json" -H "X-API-Key: org_TheAPIKeyFromStep1" -d "{\"notification_id\": \"notification_id_returned_from_step_4\"}"
    ```

## API Documentation (Swagger UI)

Interactive API documentation is available for both the Notification Gateway and the Template Service using Swagger UI, generated by `drf-spectacular`.

### For Notification Gateway (Port 8000):

*   **Schema Endpoint:** `GET /api/schema/`
    *   **Description:** Serves the OpenAPI 3.0 schema definition file for the gateway's API.
    *   **Authentication:** None required for the schema itself.
    *   **Example:** `curl -X GET http://127.0.0.1:8000/api/schema/`

*   **Swagger UI Endpoint:** `GET /api/docs/`
    *   **Description:** Renders the interactive Swagger UI interface for the gateway's API endpoints.
    *   **Authentication:** None required to load the UI page. Individual endpoints within the UI will require authentication (e.g., `X-API-Key`).
    *   **Access:** Open `http://127.0.0.1:8000/api/docs/` in your web browser.

### For Template Service (Port 8002):

*   **Schema Endpoint:** `GET /api/schema/`
    *   **Description:** Serves the OpenAPI 3.0 schema definition file for the template service's API.
    *   **Authentication:** None required for the schema itself.
    *   **Example:** `curl -X GET http://127.0.0.1:8002/api/schema/`

*   **Swagger UI Endpoint:** `GET /api/docs/`
    *   **Description:** Renders the interactive Swagger UI interface for the template service's API endpoints (including the mock user service endpoints hosted there).
    *   **Authentication:** None required to load the UI page. Individual endpoints within the UI will require authentication (e.g., `X-Internal-Secret` for internal endpoints, potentially `X-API-Key` if public endpoints are added later).
    *   **Access:** Open `http://127.0.0.1:8002/api/docs/` in your web browser.

## Troubleshooting

*   **`TemplateDoesNotExist at /api/docs/` (drf_spectacular/swagger_ui.html):**
    *   **Cause:** The `drf_spectacular` package's templates (like `swagger_ui.html`) are not found by Django's template loader. This usually means `drf_spectacular` is not correctly added to `INSTALLED_APPS` or its templates are not discoverable.
    *   **Solution:** Ensure `'drf_spectacular'` is present in the `INSTALLED_APPS` list in both `notification_gateway/settings.py` and `template_man/settings.py`.

*   **`NameError: name 'InternalAPIAuthentication' is not defined` or similar:**
    *   **Cause:** Missing import statement in the view file.
    *   **Solution:** Add `from .authentication import InternalAPIAuthentication` (or other missing classes) at the top of the file.

*   **`RuntimeError: Model class ... doesn't declare an explicit app_label...`:**
    *   **Cause:** The model class (e.g., `Organization`, `Notification`, `Template`) is not listed in `INSTALLED_APPS` in the project's `settings.py` where the view using the model resides, or the model is in an app not loaded by the project.

*   **`AttributeError: 'RedisClient' object has no attribute '_is_connected'`:**
    *   **Cause:** The `InternalAPIAuthentication.authenticate` method returned an object that `IsAuthenticated` permission could not process correctly, or the `RedisClient` initialization logic failed to set the attribute before an error occurred, or the `RedisClient` code itself has an issue.
    *   **Solution:** Ensure `authenticate` returns a tuple `(user, auth)` or `None`. Verify `RedisClient.__init__` and `_initialize` logic correctly handles setting `_is_connected`.

*   **`TypeError: cannot unpack non-iterable ... object`:**
    *   **Cause:** The `authenticate` method returned something other than a tuple `(user, auth)`.
    *   **Solution:** Ensure `authenticate` returns a tuple `(user, auth)` or `None`.

*   **`ModuleNotFoundError: No module named 'model_utils'`:**
    *   **Cause:** The `model_utils` package is not installed.
    *   **Solution:** Run `pip install model_utils`.

*   **`ModuleNotFoundError: No module named 'decouple'`:**
    *   **Cause:** The `python-decouple` package is not installed.
    *   **Solution:** Run `pip install python-decouple`.

*   **`socket.gaierror: [Errno -2] Name or service not known` (for User/Template/RabbitMQ services):**
    *   **Cause:** The hostname in `USER_SERVICE_URL`, `TEMPLATE_SERVICE_URL`, or `RABBITMQ_URL` settings cannot be resolved. This often happens if the services are running locally but the settings point to a Docker hostname (like `user-service:8000` or `rabbitmq:5672`) or a non-existent host.
    *   **Solution:** Update the `.env` file or `settings.py` to point to the correct local addresses (e.g., `http://localhost:8002`, `amqp://localhost:5672`).

*   **`ConnectionRefusedError` (for User/Template/RabbitMQ services):**
    *   **Cause:** The service URL is correct, but the target service is not running or not listening on the specified port.
    *   **Solution:** Ensure the required service (User, Template, RabbitMQ) is started and accessible.

*   **`ValueError: Cannot assign "...": "User.organization" must be a "Organization" instance.`:**
    *   **Cause:** Code is trying to assign a string ID directly to a `ForeignKey` field expecting a model instance.
    *   **Solution:** Fetch the `Organization` instance using `Organization.objects.get(id=org_id)` and assign the *instance*.

*   **`IntegrityError: UNIQUE constraint failed: ...` (when creating org/user/template):**
    *   **Cause:** Attempting to create an object with a unique field (like `api_key`, `email`, `code`) that already exists in the database.
    *   **Solution:** Use a unique value for the field, or check for existence before creating.

*   **`Template error` response: "Template service unavailable":**
    *   **Cause:** The gateway could not reach the template service or received an error (e.g., 404 if the template doesn't exist for the organization, 500 for internal errors on the template service).
    *   **Solution:** Check the template service logs, ensure the template exists and is active for the organization making the request, verify the `X-Organization-ID` header is passed correctly, and confirm the `TEMPLATE_SERVICE_URL` setting.

*   **`User not found` response: "User service unavailable":**
    *   **Cause:** The gateway could not reach the user service or received an error (e.g., 404 if the user doesn't exist for the organization, 500 for internal errors on the user service).
    *   **Solution:** Check the user service logs (hosted by template service in mock setup), ensure the user exists and belongs to the organization making the request, verify the `X-Organization-ID` header is passed correctly, and confirm the `USER_SERVICE_URL` setting.

*   **`403 Forbidden` when accessing `/api/docs/`:**
    *   **Cause:** The view handling `/api/docs/` (likely `SpectacularSwaggerView`) has authentication/permission classes applied that it shouldn't have (e.g., `InternalAPIAuthentication` and `IsAuthenticated`).
    *   **Solution:** Ensure the `SpectacularAPIView` and `SpectacularSwaggerView` URL patterns in `urls.py` are *before* any catch-all patterns and are *not* handled by views with restrictive permissions. The `drf_spectacular` views should generally be public or have minimal authentication required by the UI itself (like a global API key if desired for docs access).

## Deployment (Conceptual - e.g., Railway)

1.  **Prepare for Deployment:**
    *   Ensure `requirements.txt` lists all dependencies.
    *   Configure environment variables via Railway's dashboard/CLI (e.g., `SECRET_KEY`, `INTERNAL_API_SECRET`, `RABBITMQ_URL`, `USER_SERVICE_URL`, `TEMPLATE_SERVICE_URL`, `REDIS_URL`, `DB_*` settings if using PostgreSQL).
    *   Use a production WSGI/ASGI server like Gunicorn/Uvicorn behind a reverse proxy (Nginx).
    *   Ensure the `ALLOWED_HOSTS` setting includes your production domain.
    *   Ensure `INSTALLED_APPS` includes `'drf_spectacular'`.

2.  **Deploy to Railway:**
    *   Link your GitHub repository.
    *   Configure the build command (e.g., `pip install -r requirements.txt`).
    *   Configure the start command (e.g., `gunicorn notification_gateway.wsgi:application` or `uvicorn notification_gateway.asgi:application --host 0.0.0.0 --port $PORT`).
    *   Add necessary addons (PostgreSQL, Redis, RabbitMQ).
    *   Ensure environment variables are correctly set in the Railway deployment environment.

## Best Practices

### 1. Always Use Idempotency Keys

*   **Good (Gateway):**
    ```python
    # When sending notification request
    response = requests.post(
        url,
        json={
            'notification_type': 'email',
            'user_id': 'user_abc123...',
            'template_code': 'welcome_email',
            'variables': {'name': 'John'},
            'request_id': f'notif-{user_id}-welcome-{int(time.time())}', # ✅ Unique and deterministic-ish
            # ... other data ...
        }
    )
    # Gateway handles idempotency internally using this request_id
    ```
*   **Bad (Gateway - potentially creates duplicates):**
    ```python
    # Sending without a specific request_id (gateway auto-generates, might not prevent all duplicates)
    response = requests.post(url, json={...}) # ❌ Relies on auto-generation
    ```

### 2. Handle Rate Limits Gracefully (Gateway Client Perspective)

*   **Example Client Logic (Conceptual):**
    ```python
    import time
    import random

    def send_notification_with_retry(payload, max_retries=3):
        for attempt in range(max_retries):
            response = requests.post('http://gateway/api/v1/notifications/', json=payload, headers={'X-API-Key': '...'})
            if response.status_code == 202:
                return response.json() # Success
            elif response.status_code == 429:
                if attempt < max_retries - 1:
                    # Calculate delay with exponential backoff and jitter
                    base_delay = 2 ** attempt
                    jitter = random.uniform(0, 1)
                    delay = base_delay + jitter
                    logger.warning(f"Rate limit hit, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    logger.error("Max retries reached after rate limiting.")
                    break # Or handle failure
            else:
                # Handle other errors (400, 401, 500, etc.)
                break # Or handle accordingly
        return response.json() # Or raise an exception
    ```

### 3. Secure API Keys

*   Store API keys securely (e.g., environment variables, secrets management).
*   Use HTTPS in production.
*   Rotate API keys periodically.

### 4. Validate Input Thoroughly

*   Use DRF Serializers for request validation whenever possible.
*   Validate variables against template requirements.

### 5. Monitor and Log Effectively

*   Use correlation IDs for tracing requests across services.
*   Log errors with sufficient context (correlation ID, user ID, template code).
*   Expose Prometheus metrics for monitoring system health and performance.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

