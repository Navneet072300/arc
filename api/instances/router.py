import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.user import User
from api.db.session import get_db
from api.dependencies import get_current_user
from api.instances import schemas, service
from api.k8s.client import get_k8s_client

router = APIRouter(prefix="/instances", tags=["instances"])


@router.get("", response_model=list[schemas.InstanceResponse])
async def list_instances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_instances(db, current_user.id)


@router.post("", response_model=schemas.InstanceCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_instance(
    body: schemas.CreateInstanceRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_client = get_k8s_client()
    instance, password, replication_password = await service.create_instance(
        db, api_client, current_user.id, body.model_dump()
    )

    # Provision K8s resources in background; client polls /instances/{id}/status
    background_tasks.add_task(
        service.run_provisioning, db, api_client, instance, password, replication_password
    )

    conn_str = service._connection_string(instance, password) if instance.external_host else None
    return schemas.InstanceCreatedResponse(
        **schemas.InstanceResponse.model_validate(instance).model_dump(),
        connection_string=conn_str,
        password=password,
    )


@router.get("/{instance_id}", response_model=schemas.InstanceDetailResponse)
async def get_instance(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    conn_str = service._connection_string(instance) if instance.external_host else None
    return schemas.InstanceDetailResponse(
        **schemas.InstanceResponse.model_validate(instance).model_dump(),
        connection_string=conn_str,
    )


@router.get("/{instance_id}/status", response_model=schemas.InstanceStatusResponse)
async def get_instance_status(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return schemas.InstanceStatusResponse(
        id=instance.id,
        status=instance.status,
        external_host=instance.external_host,
        external_port=instance.external_port,
    )


@router.patch("/{instance_id}", response_model=schemas.InstanceResponse)
async def update_instance(
    instance_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if "name" in body:
        instance.name = body["name"]
        await db.commit()
        await db.refresh(instance)
    return instance


@router.delete("/{instance_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_instance(
    instance_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status in ("deleting", "deleted"):
        raise HTTPException(status_code=400, detail=f"Instance is already {instance.status}")
    api_client = get_k8s_client()
    background_tasks.add_task(service.delete_instance, db, api_client, instance)
    return {"detail": "Deletion initiated", "id": str(instance_id)}


@router.get("/{instance_id}/replicas", response_model=list[schemas.ReadReplicaResponse])
async def list_replicas(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return await service.list_replicas(db, instance)


@router.post(
    "/{instance_id}/replicas",
    response_model=schemas.ReadReplicaResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_replica(
    instance_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "running":
        raise HTTPException(status_code=400, detail="Primary instance must be running to add a replica")
    api_client = get_k8s_client()
    replica = await service.create_replica(db, api_client, instance)
    background_tasks.add_task(service.run_replica_provisioning, db, api_client, instance, replica)
    return replica


@router.delete(
    "/{instance_id}/replicas/{replica_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_replica(
    instance_id: uuid.UUID,
    replica_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    replicas = await service.list_replicas(db, instance)
    replica = next((r for r in replicas if r.id == replica_id), None)
    if not replica:
        raise HTTPException(status_code=404, detail="Replica not found")
    if replica.status in ("deleting", "deleted"):
        raise HTTPException(status_code=400, detail=f"Replica is already {replica.status}")
    api_client = get_k8s_client()
    background_tasks.add_task(service.delete_replica, db, api_client, instance, replica)
    return {"detail": "Replica deletion initiated", "id": str(replica_id)}


@router.post("/{instance_id}/suspend", status_code=status.HTTP_200_OK)
async def suspend_instance(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "running":
        raise HTTPException(status_code=400, detail="Only running instances can be suspended")
    api_client = get_k8s_client()
    await service.suspend_instance(db, api_client, instance)
    return {"detail": "Instance suspended", "id": str(instance_id)}


@router.post("/{instance_id}/resume", status_code=status.HTTP_200_OK)
async def resume_instance(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "suspended":
        raise HTTPException(status_code=400, detail="Only suspended instances can be resumed")
    api_client = get_k8s_client()
    await service.resume_instance(db, api_client, instance)
    return {"detail": "Instance resumed", "id": str(instance_id)}


@router.post("/{instance_id}/credentials/rotate", response_model=schemas.CredentialsRotateResponse)
async def rotate_credentials(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instance = await service.get_instance(db, current_user.id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status != "running":
        raise HTTPException(status_code=400, detail="Instance is not running")
    api_client = get_k8s_client()
    new_password, conn_str = await service.rotate_credentials(db, api_client, instance)
    return schemas.CredentialsRotateResponse(
        connection_string=conn_str,
        password=new_password,
        username=instance.pg_username,
        host=instance.external_host,
        port=instance.external_port,
        database=instance.pg_db_name,
    )
