"""
Filters API
~~~~~~~~~~~

REST API endpoints for filter CRUD operations.

Endpoints:
- GET /api/filters - List all filters
- GET /api/filters/{id} - Get single filter
- POST /api/filters - Create filter
- PUT /api/filters/{id} - Update filter
- DELETE /api/filters/{id} - Delete filter
- PATCH /api/filters/{id}/toggle - Toggle enabled status
- POST /api/filters/{id}/clone - Clone filter
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends

from ..models.filter import (
    FilterCreate,
    FilterUpdate,
    FilterResponse,
    parse_filter_config
)
from ..screener.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filters", tags=["filters"])


# ============================================
# Dependency: Get Database
# ============================================

async def get_db() -> Database:
    """Get database instance (dependency injection)."""
    from ..main import app
    return app.state.db


# ============================================
# Endpoints
# ============================================

@router.get("", response_model=list[FilterResponse])
async def list_filters(
    type: Optional[str] = Query(None, description="Filter by type"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    db: Database = Depends(get_db)
):
    """
    Get list of all filters.
    
    Query parameters:
        type: Filter by type ('price_change' or 'volume_spike')
        enabled: Filter by enabled status
    
    Returns:
        List of filters
    """
    try:
        # Get all filters
        filters = await db.get_all_filters(enabled_only=False)
        
        # Apply filters
        if type:
            filters = [f for f in filters if f['type'] == type]
        
        if enabled is not None:
            filters = [f for f in filters if f['enabled'] == enabled]
        
        # Add last_trigger timestamp
        result = []
        for f in filters:
            # Get last trigger for this filter
            cursor = await db.db.execute("""
                SELECT MAX(triggered_at) as last_trigger
                FROM filter_triggers
                WHERE filter_id = ?
            """, (f['id'],))
            
            row = await cursor.fetchone()
            last_trigger = row['last_trigger'] if row else None
            
            result.append({
                **f,
                'last_trigger': last_trigger
            })
        
        logger.info(f"📋 Listed {len(result)} filters")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error listing filters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{filter_id}", response_model=FilterResponse)
async def get_filter(
    filter_id: int,
    db: Database = Depends(get_db)
):
    """
    Get single filter by ID.
    
    Path parameters:
        filter_id: Filter ID
    
    Returns:
        Filter details
    
    Raises:
        404: Filter not found
    """
    try:
        filter_data = await db.get_filter(filter_id)
        
        if not filter_data:
            raise HTTPException(status_code=404, detail="Filter not found")
        
        # Get last trigger
        cursor = await db.db.execute("""
            SELECT MAX(triggered_at) as last_trigger
            FROM filter_triggers
            WHERE filter_id = ?
        """, (filter_id,))
        
        row = await cursor.fetchone()
        filter_data['last_trigger'] = row['last_trigger'] if row else None
        
        logger.info(f"📄 Retrieved filter #{filter_id}")
        
        return filter_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting filter {filter_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=FilterResponse, status_code=201)
async def create_filter(
    filter_data: FilterCreate,
    db: Database = Depends(get_db)
):
    """
    Create new filter.
    
    Request body:
        FilterCreate model
    
    Returns:
        Created filter
    """
    try:
        # Convert config to dict
        config_dict = filter_data.config.model_dump()
        
        # Create filter in database
        filter_id = await db.create_filter(
            name=filter_data.name,
            filter_type=filter_data.type,
            config=config_dict,
            enabled=filter_data.enabled
        )
        
        # Retrieve created filter
        created = await db.get_filter(filter_id)
        created['last_trigger'] = None
        
        logger.info(
            f"✅ Created filter #{filter_id}: {filter_data.name} ({filter_data.type})"
        )
        
        return created
        
    except Exception as e:
        logger.error(f"❌ Error creating filter: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{filter_id}", response_model=FilterResponse)
async def update_filter(
    filter_id: int,
    filter_data: FilterUpdate,
    db: Database = Depends(get_db)
):
    """
    Update filter.
    
    Path parameters:
        filter_id: Filter ID
    
    Request body:
        FilterUpdate model (all fields optional)
    
    Returns:
        Updated filter
    
    Raises:
        404: Filter not found
    """
    try:
        # Check filter exists
        existing = await db.get_filter(filter_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Filter not found")
        
        # Prepare update data
        config_dict = None
        if filter_data.config:
            config_dict = filter_data.config.model_dump()
        
        # Update filter
        success = await db.update_filter(
            filter_id=filter_id,
            name=filter_data.name,
            enabled=filter_data.enabled,
            config=config_dict
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Update failed")
        
        # Retrieve updated filter
        updated = await db.get_filter(filter_id)
        
        # Get last trigger
        cursor = await db.db.execute("""
            SELECT MAX(triggered_at) as last_trigger
            FROM filter_triggers
            WHERE filter_id = ?
        """, (filter_id,))
        
        row = await cursor.fetchone()
        updated['last_trigger'] = row['last_trigger'] if row else None
        
        logger.info(f"✅ Updated filter #{filter_id}")
        
        return updated
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating filter {filter_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{filter_id}", status_code=204)
async def delete_filter(
    filter_id: int,
    db: Database = Depends(get_db)
):
    """
    Delete filter.
    
    Path parameters:
        filter_id: Filter ID
    
    Raises:
        404: Filter not found
    """
    try:
        # Check filter exists
        existing = await db.get_filter(filter_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Filter not found")
        
        # Delete filter
        success = await db.delete_filter(filter_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Delete failed")
        
        logger.info(f"🗑️  Deleted filter #{filter_id}")
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting filter {filter_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{filter_id}/toggle")
async def toggle_filter(
    filter_id: int,
    db: Database = Depends(get_db)
):
    """
    Toggle filter enabled status.
    
    Path parameters:
        filter_id: Filter ID
    
    Returns:
        Updated enabled status
    
    Raises:
        404: Filter not found
    """
    try:
        # Get current filter
        filter_data = await db.get_filter(filter_id)
        if not filter_data:
            raise HTTPException(status_code=404, detail="Filter not found")
        
        # Toggle enabled
        new_enabled = not filter_data['enabled']
        
        success = await db.update_filter(
            filter_id=filter_id,
            enabled=new_enabled
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Toggle failed")
        
        logger.info(
            f"🔄 Toggled filter #{filter_id}: "
            f"{'enabled' if new_enabled else 'disabled'}"
        )
        
        return {
            "id": filter_id,
            "enabled": new_enabled
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error toggling filter {filter_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{filter_id}/clone", response_model=FilterResponse, status_code=201)
async def clone_filter(
    filter_id: int,
    db: Database = Depends(get_db)
):
    """
    Clone (duplicate) filter.
    
    Path parameters:
        filter_id: Filter ID to clone
    
    Returns:
        Cloned filter (with " (copy)" appended to name)
    
    Raises:
        404: Filter not found
    """
    try:
        # Get original filter
        original = await db.get_filter(filter_id)
        if not original:
            raise HTTPException(status_code=404, detail="Filter not found")
        
        # Create clone with modified name
        cloned_name = f"{original['name']} (copy)"
        
        new_filter_id = await db.create_filter(
            name=cloned_name,
            filter_type=original['type'],
            config=original['config'],
            enabled=False  # Cloned filters start disabled
        )
        
        # Retrieve cloned filter
        cloned = await db.get_filter(new_filter_id)
        cloned['last_trigger'] = None
        
        logger.info(
            f"📋 Cloned filter #{filter_id} → #{new_filter_id}"
        )
        
        return cloned
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error cloning filter {filter_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
