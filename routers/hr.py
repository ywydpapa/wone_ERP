from fastapi import APIRouter, Depends

from core.deps import require_staff
from routers.hr_employee import router as emp_router
from routers.hr_attendance import router as att_router
from routers.hr_insurance_rates import router as rates_router

router = APIRouter()
router.include_router(emp_router, prefix="/hr", dependencies=[Depends(require_staff)])
router.include_router(att_router, prefix="/hr", dependencies=[Depends(require_staff)])
router.include_router(rates_router, prefix="/hr", dependencies=[Depends(require_staff)])
