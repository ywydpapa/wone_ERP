from fastapi import APIRouter

from routers.hr_employee import router as emp_router
from routers.hr_attendance import router as att_router
from routers.hr_roster import router as roster_router
from routers.hr_payroll import router as payroll_router
from routers.hr_insurance_rates import router as rates_router

router = APIRouter()
router.include_router(emp_router, prefix="/hr")
router.include_router(att_router, prefix="/hr")
router.include_router(roster_router, prefix="/hr")
router.include_router(payroll_router, prefix="/hr")
router.include_router(rates_router, prefix="/hr")
