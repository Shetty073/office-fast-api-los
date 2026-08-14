# Orchestration Engine

The **SCF LOS Orchestration Engine** is designed to execute sequences of third-party API services asynchronously. It enables data passing (chaining) between steps, automatic retries, and comprehensive performance logging.

---

## Architecture Overview

The orchestration workflow consists of:
1. **Trigger API (`POST /api/chain/trigger`)**: Receives the sequence of service names, initial inputs, and inter-service field mappings. It creates a database execution record and triggers the execution in a background worker thread using FastAPI's `BackgroundTasks`.
2. **Orchestrator (`orchestrator.py`)**: Manages the step-by-step lifecycle of the sequence. It copies static inputs, resolves field mappings from previous step outputs, runs services, and handles partial success or critical failures.
3. **Execution Schema (`database.db`)**: Saves the status (`PENDING`, `RUNNING`, `COMPLETED`, `PARTIAL_SUCCESS`, `FAILED`) and step latency data into `SequenceExecution`.

---

## Inter-Service Data Mapping

To pass outputs from a previous API as inputs to the next API in a sequence, define mappings in the `mappings` list of your trigger payload.

### Mapping Rule Syntax
Each mapping rule is an object:
* `from_service`: The name of the source service (e.g. `"todo_service"`).
* `from_field`: The dot-notated path to resolve inside the source service's **response data block** (`response["data"]`).
* `to_service`: The name of the target service (e.g. `"post_service"`).
* `to_field`: The dot-notated path in the target service's input payload to populate.

### Where to Define Mappings
Mappings are defined dynamically in the trigger request body.

#### Example Payload:
```json
{
    "sequence": [
        "todo_service",
        "post_service"
    ],
    "inputs": {
        "todo_service": {
            "todo_id": 2
        },
        "post_service": {
            "body": "Static post description"
        }
    },
    "mappings": [
        {
            "from_service": "todo_service",
            "from_field": "title",
            "to_service": "post_service",
            "to_field": "title"
        }
    ]
}
```
*In this example:*
1. `todo_service` runs first. Its output `data` block is:
   ```json
   {
       "userId": 1,
       "id": 2,
       "title": "quis ut nam facilis et officia qui",
       "completed": false
   }
   ```
2. The orchestrator extracts `"title"` (since `from_field` is `"title"`).
3. It merges/writes that value into the `post_service` payload at key `"title"` (since `to_field` is `"title"`).
4. `post_service` executes with:
   ```json
   {
       "title": "quis ut nam facilis et officia qui",
       "body": "Static post description"
   }
   ```
