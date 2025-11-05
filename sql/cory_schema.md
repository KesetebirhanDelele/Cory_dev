%% ----------------------------------------------------------
%% 🧩 CORY DATABASE — COLOR-CODED ER DIAGRAM
%% ----------------------------------------------------------
%% Tip: Use the Markdown Preview Mermaid Support extension in VS Code
%% ----------------------------------------------------------

erDiagram

    %% === TENANT & ORGANIZATION STRUCTURE (🟧 Orange) ===
    classDef org fill:#FBC02D,stroke:#333,stroke-width:1px,color:#000;

    TENANT:::org {
        uuid id PK
        text name```mermaid
        timestamptz created_at
    }

    PROJECT:::org {
        uuid id PK
        text name
        uuid tenant_id FK
        timestamptz created_at
    }

    ORGANIZATIONS:::org {
        uuid id PK
        text name
        text slug
        text domain
        text phone
        text timezone
        text website
        jsonb address
        boolean is_active
    }

    USERS:::org {
        uuid id PK
        uuid organization_id FK
        text email
        text first_name
        text last_name
        text role
        boolean is_active
    }

    ORGANIZATION_SETTINGS:::org {
        uuid id PK
        uuid organization_id FK
        text setting_key
        jsonb setting_value
    }

    ORGANIZATION_INTEGRATIONS:::org {
        uuid id PK
        uuid organization_id FK
        text integration_name
        text integration_type
    }

    %% === CORE ENTITIES (🟦 Blue) ===
    classDef core fill:#64B5F6,stroke:#333,stroke-width:1px,color:#000;

    CAMPAIGNS:::core {
        uuid id PK
        uuid organization_id FK
        text name
        text description
        boolean is_active
    }

    CONTACT:::core {
        uuid id PK
        uuid project_id FK
        text first_name
        text last_name
        text email
        text phone
    }

    ENROLLMENT:::core {
        uuid id PK
        uuid project_id FK
        uuid campaign_id FK
        uuid contact_id FK
        text status
    }

    %% === COMMUNICATION ENTITIES (🟪 Purple) ===
    classDef comm fill:#CE93D8,stroke:#333,stroke-width:1px,color:#000;

    MESSAGE:::comm {
        uuid id PK
        uuid enrollment_id FK
        text channel
        text direction
    }

    EVENT:::comm {
        uuid id PK
        uuid enrollment_id FK
        text event_type
        text direction
    }

    OUTCOME:::comm {
        uuid id PK
        uuid enrollment_id FK
        text kind
        text value
    }

    HANDOFF:::comm {
        uuid id PK
        uuid enrollment_id FK
        text status
        text assignee
    }

    %% === TEMPLATES & CAMPAIGNS (🟩 Green) ===
    classDef asset fill:#81C784,stroke:#333,stroke-width:1px,color:#000;

    TEMPLATE:::asset {
        uuid id PK
        uuid project_id FK
        text name
        text channel
    }

    TEMPLATE_VARIANT:::asset {
        uuid id PK
        uuid template_id FK
        text name
    }

    LEAD_CAMPAIGN_STEPS:::asset {
        uuid id PK
        uuid registration_id FK
        text step_name
        text step_type
    }

    APPOINTMENTS:::asset {
        uuid id PK
        uuid project_id FK
        uuid campaign_id FK
        timestamptz scheduled_for
    }

    NURTURE_CAMPAIGNS:::asset {
        uuid id PK
        uuid organization_id FK
        text name
        text goal
    }

    REENGAGEMENT_CAMPAIGNS:::asset {
        uuid id PK
        uuid organization_id FK
        text name
        text trigger_condition
    }

    %% ==========================================================
    %% RELATIONSHIPS
    %% ==========================================================
    TENANT ||--o{ PROJECT : "owns"
    PROJECT ||--o{ CONTACT : "collects"
    PROJECT ||--o{ ENROLLMENT : "tracks"
    ORGANIZATIONS ||--o{ USERS : "has"
    ORGANIZATIONS ||--o{ CAMPAIGNS : "runs"
    ORGANIZATIONS ||--o{ ORGANIZATION_SETTINGS : "configures"
    ORGANIZATIONS ||--o{ ORGANIZATION_INTEGRATIONS : "integrates"
    CAMPAIGNS ||--o{ ENROLLMENT : "assigned"
    CONTACT ||--o{ ENROLLMENT : "participates"
    ENROLLMENT ||--o{ MESSAGE : "triggers"
    ENROLLMENT ||--o{ EVENT : "records"
    ENROLLMENT ||--o{ OUTCOME : "produces"
    ENROLLMENT ||--o{ HANDOFF : "escalates"
    ENROLLMENT ||--o{ LEAD_CAMPAIGN_STEPS : "progresses"
    TEMPLATE ||--o{ TEMPLATE_VARIANT : "has"
    ORGANIZATIONS ||--o{ NURTURE_CAMPAIGNS : "owns"
    ORGANIZATIONS ||--o{ REENGAGEMENT_CAMPAIGNS : "owns"
