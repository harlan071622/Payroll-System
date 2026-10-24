from datetime import datetime, timedelta
from typing import Callable, Optional

import flet as ft

import database as db
import reports
from database import AdminExpenseItem, EquipmentItem, ExpenseItem, LaborItem, MaterialItem, Project

NUMERIC_FILTER = ft.InputFilter(regex_string=r"^\d*\.?\d*$", allow=True, replacement_string="")
AMOUNT_FILTER = ft.InputFilter(regex_string=r"^[\d,]*\.?\d*[kKmMbB]?$", allow=True, replacement_string="")

AMOUNT_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# (name, skill, daily rate)
WORKERS: list[tuple[str, str, int]] = [
    ("Weng", "Welder", 850),
    ("Marlon", "Carpenter", 800),
    ("Mark", "Mason", 800),
    ("Alven", "Plumber", 750),
    ("Donjie", "Electrician", 1000),
    ("Jayson", "Labor", 600),
    ("Jomer", "Steelman", 750),
]

WORKER_INFO: dict[str, tuple[str, int]] = {name: (skill, rate) for name, skill, rate in WORKERS}
PAYROLL_ROW_COUNT = 20

def to_float(value: Optional[str]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_amount(value: Optional[str]) -> float:
    if not value:
        return 0.0
    text = value.strip().lower().replace(",", "").replace("₱", "")
    if not text:
        return 0.0
    multiplier = 1
    if text[-1] in AMOUNT_SUFFIXES:
        multiplier = AMOUNT_SUFFIXES[text[-1]]
        text = text[:-1]
    try:
        return round(float(text) * multiplier, 2)
    except (TypeError, ValueError):
        return 0.0


def format_plain_amount(value: float) -> str:
    """Format a number for an editable field: comma-grouped, no scientific notation."""
    if not value:
        return ""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def notify(page: ft.Page, message: str, error: bool = False) -> None:
    snack = ft.SnackBar(content=ft.Text(message), bgcolor=ft.Colors.ERROR if error else None, open=True)
    page.overlay.append(snack)
    page.update()


async def export_project_report(page: ft.Page, file_picker: ft.FilePicker, project: Project, kind: str) -> None:
    extension = {"pdf": "pdf", "docx": "docx", "csv": "csv"}[kind]
    path = await file_picker.save_file(
        dialog_title=f"Export {extension.upper()} report",
        file_name=f"{project.name}_report.{extension}",
        file_type=ft.FilePickerFileType.CUSTOM,
        allowed_extensions=[extension],
    )
    if not path:
        return
    if not path.lower().endswith(f".{extension}"):
        path += f".{extension}"
    try:
        if kind == "pdf":
            reports.export_pdf(project, path)
        elif kind == "docx":
            reports.export_docx(project, path)
        else:
            reports.export_csv(project, path)
    except OSError as exc:
        notify(page, f"Export failed: {exc}", error=True)
        return
    notify(page, f"Exported to {path}")

class MaterialRow:
    """A single committed material line, entered via the delivery-receipt popup.

    Unlike the other row types, this is a read-only display line (not live-editable
    fields) since its data comes from the Add Material modal. Correcting an entry
    means deleting it and re-adding it through the modal.
    """
    def __init__(self, on_delete: Callable[["MaterialRow"], None], dr_no: str = "", date: str = "",
                 supplier: str = "", name: str = "", qty_number: float = 0.0, qty_unit: str = "",
                 total_price: float = 0.0):
        self.on_delete = on_delete
        self.dr_no = dr_no
        self.date = date
        self.supplier = supplier
        self.name = name
        self.qty_number = qty_number
        self.qty_unit = qty_unit
        self.total_price = total_price

        self.delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                            tooltip="Remove", on_click=lambda e: self.on_delete(self))

    @property
    def total(self) -> float:
        return round(self.total_price, 2)

    def has_content(self) -> bool:
        return bool(self.name.strip())

    def to_item(self) -> MaterialItem:
        return MaterialItem(
            name=self.name, qty_number=self.qty_number, qty_unit=self.qty_unit,
            total_price=self.total_price, dr_no=self.dr_no, date=self.date, supplier=self.supplier,
        )

class LaborRow:
    """A single committed payroll line, entered via the Add Payroll popup."""
    def __init__(self, on_delete: Callable[["LaborRow"], None], payroll_no: str = "", date_start: str = "",
                 date_end: str = "", worker: str = "", skill: str = "", rate: float = 0.0,
                 days_marked: Optional[list[str]] = None, cash_advance: float = 0.0,
                 overtime_hours: float = 0.0):
        self.on_delete = on_delete
        self.payroll_no = payroll_no
        self.date_start = date_start
        self.date_end = date_end
        self.worker = worker
        self.skill = skill
        self.rate = rate
        self.days_marked = sorted(days_marked or [])
        self.cash_advance = cash_advance
        self.overtime_hours = overtime_hours

        self.delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                            tooltip="Remove", on_click=lambda e: self.on_delete(self))

    @property
    def days(self) -> int:
        return len(self.days_marked)

    @property
    def overtime_pay(self) -> float:
        return round((self.rate / 8) * self.overtime_hours, 2)

    @property
    def total(self) -> float:
        return round(self.days * self.rate + self.overtime_pay - self.cash_advance, 2)

    def days_display(self) -> str:
        return " / ".join(d[5:] for d in self.days_marked) if self.days_marked else "—"

    def has_content(self) -> bool:
        return bool(self.worker.strip()) and bool(self.days_marked)

    def to_item(self) -> LaborItem:
        return LaborItem(worker=self.worker, rate=self.rate, skill=self.skill, days_marked=self.days_marked,
                          payroll_no=self.payroll_no, date_start=self.date_start, date_end=self.date_end,
                          cash_advance=self.cash_advance, overtime_hours=self.overtime_hours)

class EquipmentRow:
    def __init__(self, on_change: Callable[[], None], on_delete: Callable[["EquipmentRow"], None],
                equipment: str = "", days: str = "", rate: str = ""):
        self.on_change = on_change
        self.on_delete = on_delete

        self.equipment_field = ft.TextField(label="Equipement", value=equipment, expand=3, on_change=self._changed)
        self.days_field = ft.TextField(label="Days", value=days, width=90, input_filter=NUMERIC_FILTER,
                                       keyboard_type=ft.KeyboardType.NUMBER, on_change=self._changed)
        self.rate_field = ft.TextField(label="Rate", value=rate, width=120, prefix="₱", input_filter=NUMERIC_FILTER,
                                        keyboard_type=ft.KeyboardType.NUMBER, on_change=self._changed)
        self.total_text = ft.Text("₱0.00", width=100, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT)
        self.delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                            tooltip="Remove", on_click=lambda e: self.on_delete(self))
        self.row = ft.Row(
            controls=[self.equipment_field, self.days_field, self.rate_field, self.total_text, self.delete_button],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._refresh_total()

    def _changed(self, e:ft.ControlEvent) -> None:
        self._refresh_total()
        self.on_change()

    def _refresh_total(self) -> None:
            self.total_text.value = f"₱{self.total:,.2f}"
    
    @property
    def days(self) -> float:
        return to_float(self.days_field.value)
    
    @property
    def rate(self) -> float:
        return to_float(self.rate_field.value)
    
    @property
    def total(self) -> float:
        return round(self.days * self.rate, 2)
    
    def has_content(self) -> bool:
        return bool((self.equipment_field.value or "").strip())
    
    def to_item(self) -> EquipmentItem:
        return EquipmentItem(equipment=(self.equipment_field.value or "").strip(), days=self.days, rate=self.rate)

class ExpenseRow:
    """A single committed expense line, entered via the Add Expense popup."""
    def __init__(self, on_delete: Callable[["ExpenseRow"], None], receipt_no: str = "", date: str = "",
                 paid_to: str = "", description: str = "", amount: float = 0.0):
        self.on_delete = on_delete
        self.receipt_no = receipt_no
        self.date = date
        self.paid_to = paid_to
        self.description = description
        self.amount = amount

        self.delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                            tooltip="Remove", on_click=lambda e: self.on_delete(self))
        self.row = ft.Row(
            controls=[
                ft.Text(receipt_no, width=100),
                ft.Text(date, width=100),
                ft.Text(paid_to, width=140),
                ft.Text(description, expand=True),
                ft.Text(f"₱{amount:,.2f}", width=120, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT),
                self.delete_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    @property
    def total(self) -> float:
        return round(self.amount, 2)

    def has_content(self) -> bool:
        return bool(self.description.strip())

    def to_item(self) -> ExpenseItem:
        return ExpenseItem(description=self.description, amount=self.amount, receipt_no=self.receipt_no,
                            date=self.date, paid_to=self.paid_to)

class AdminExpenseRow:
    """A single committed admin expense line, entered via the Add Admin Expense popup."""
    def __init__(self, on_delete: Callable[["AdminExpenseRow"], None], receipt_no: str = "", date: str = "",
                 paid_to: str = "", description: str = "", amount: float = 0.0):
        self.on_delete = on_delete
        self.receipt_no = receipt_no
        self.date = date
        self.paid_to = paid_to
        self.description = description
        self.amount = amount

        self.delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                            tooltip="Remove", on_click=lambda e: self.on_delete(self))
        self.row = ft.Row(
            controls=[
                ft.Text(receipt_no, width=100),
                ft.Text(date, width=100),
                ft.Text(paid_to, width=140),
                ft.Text(description, expand=True),
                ft.Text(f"₱{amount:,.2f}", width=120, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT),
                self.delete_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    @property
    def total(self) -> float:
        return round(self.amount, 2)

    def has_content(self) -> bool:
        return bool(self.description.strip())

    def to_item(self) -> AdminExpenseItem:
        return AdminExpenseItem(description=self.description, amount=self.amount, receipt_no=self.receipt_no,
                                 date=self.date, paid_to=self.paid_to)

def build_list_view(page: ft.Page) -> ft.View:
    file_picker = ft.FilePicker()
    try:
        projects = db.list_projects()
        load_error = None
    except ConnectionError as exc:
        projects = []
        load_error = str(exc)

    def project_card(project: Project) -> ft.Card:
        def open_edit(e: ft.ControlEvent) -> None:
            page.go(f"/project/edit/{project.id}")

        def confirm_delete(e: ft.ControlEvent) -> None:
            def do_delete(e: ft.ControlEvent) -> None:
                db.delete_project(project.id)
                dialog.open = False
                page.views[-1] = build_list_view(page)
                page.update()
                notify(page, f'Deleted "{project.name}".')

            def cancel(e: ft.ControlEvent) -> None:
                dialog.open = False
                page.update()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete project?"),
                content=ft.Text(f'This will permanently delete "{project.name}" and all its line items.'),
                actions=[
                    ft.TextButton(content="Cancel", on_click=cancel),
                    ft.TextButton(content="Delete", style=ft.ButtonStyle(color=ft.Colors.RED_400), on_click=do_delete),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(dialog)
            dialog.open = True
            page.update()

        async def export_pdf_clicked(e: ft.ControlEvent) -> None:
            await export_project_report(page, file_picker, project, "pdf")

        async def export_docx_clicked(e: ft.ControlEvent) -> None:
            await export_project_report(page, file_picker, project, "docx")

        async def export_csv_clicked(e: ft.ControlEvent) -> None:
            await export_project_report(page, file_picker, project, "csv")

        return ft.Card(
            content=ft.Container(
                padding=16,
                content=ft.Column(
                    spacing=6,
                    controls=[
                        ft.Container(
                            ink=True,
                            on_click=open_edit,
                            content=ft.Column(
                                spacing=6,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        controls=[
                                            ft.Text(project.name, size=16, weight=ft.FontWeight.W_500),
                                            ft.Text(f"₱{project.total_cost:,.2f}", size=16,
                                                    weight=ft.FontWeight.BOLD),
                                        ],
                                    ),
                                    *([ft.Text(project.description, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)]
                                      if project.description else []),
                                    *([ft.Text(
                                        "   ·   ".join(filter(None, [
                                            f"Location: {project.location}" if project.location else "",
                                            f"Budget: ₱{project.budget:,.2f}" if project.budget else "",
                                        ])),
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    )] if project.location or project.budget else []
                                    ),
                                ],
                            ),
                        ),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.END,
                            controls=[
                                ft.PopupMenuButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    tooltip="Export report",
                                    items=[
                                        ft.PopupMenuItem(content="PDF", icon=ft.Icons.PICTURE_AS_PDF,
                                                          on_click=export_pdf_clicked),
                                        ft.PopupMenuItem(content="Word", icon=ft.Icons.DESCRIPTION,
                                                          on_click=export_docx_clicked),
                                        ft.PopupMenuItem(content="CSV", icon=ft.Icons.TABLE_CHART,
                                                          on_click=export_csv_clicked),
                                    ],
                                ),
                                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Delete",
                                              icon_color=ft.Colors.RED_400, on_click=confirm_delete),
                            ],
                        ),
                    ],
                ),
            ),
        )

    if load_error:
        body = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.CLOUD_OFF, size=56, color=ft.Colors.ERROR),
                ft.Text("Can't reach the database", size=16, weight=ft.FontWeight.W_500),
                ft.Container(
                    padding=ft.Padding(left=40, right=40, top=0, bottom=0),
                    content=ft.Text(load_error, text_align=ft.TextAlign.CENTER,
                                     color=ft.Colors.ON_SURFACE_VARIANT),
                ),
            ],
        )
    elif not projects:
        body = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.CONSTRUCTION, size=56, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("No projects yet", size=16, weight=ft.FontWeight.W_500),
                ft.Text('Tap "New Project" to add your first one.', color=ft.Colors.ON_SURFACE_VARIANT),
            ],
        )
    else:
        body = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            controls=[project_card(p) for p in projects],
        )

    return ft.View(
        route="/",
        appbar=ft.AppBar(
            title=ft.Text("Construction Projects"),
            center_title=False,
        ),
        floating_action_button=ft.FloatingActionButton(
            icon=ft.Icons.ADD, content="New Project", on_click=lambda e: page.go("/project/new"),
        ),
        padding=ft.Padding.all(16),
        services=[file_picker],
        controls=[body],
    )


def build_not_found_view(page: ft.Page, route: str) -> ft.View:
    return ft.View(
        route=route,
        appbar=ft.AppBar(title=ft.Text("Project not found")),
        padding=ft.Padding.all(16),
        controls=[
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text("This project no longer exists.", size=16, weight=ft.FontWeight.W_500),
                    ft.ElevatedButton(content="Back to projects", on_click=lambda e: page.go("/")),
                ],
            ),
        ],
    )


def build_edit_view(page: ft.Page, project_id: Optional[str]) -> ft.View:
    if project_id:
        project = db.get_project(project_id)
        if project is None:
            return build_not_found_view(page, f"/project/edit/{project_id}")
    else:
        project = Project(id=None, name="")

    name_field = ft.TextField(label="Project Name", value=project.name, autofocus=True, expand=True)
    description_field = ft.TextField(label="Description", value=project.description, expand=True,
                                      multiline=True, min_lines=2, max_lines=4)
    location_field = ft.TextField(label="Project Location", value=project.location, expand=True)
    budget_field = ft.TextField(label="Project Budget", value=format_plain_amount(project.budget),
                                 expand=True, prefix="₱", input_filter=AMOUNT_FILTER,
                                 hint_text="e.g. 500k, 1.5m")

    def budget_blur(e: ft.ControlEvent) -> None:
        budget_field.value = format_plain_amount(parse_amount(budget_field.value))
        page.update()

    budget_field.on_blur = budget_blur

    material_rows: list[MaterialRow] = []
    labor_rows: list[LaborRow] = []
    equipment_rows: list[EquipmentRow] = []
    expense_rows: list[ExpenseRow] = []
    admin_expense_rows: list[AdminExpenseRow] = []
    materials_column = ft.Column(spacing=8)
    labor_column = ft.Column(spacing=8)
    equipment_column = ft.Column(spacing=8)
    expenses_column = ft.Column(spacing=8)
    admin_expenses_column = ft.Column(spacing=8)

    materials_total_text = ft.Text("₱0.00", weight=ft.FontWeight.BOLD)
    labor_total_text = ft.Text("₱0.00", weight=ft.FontWeight.BOLD)
    equipment_total_text = ft.Text("₱0.00", weight=ft.FontWeight.BOLD)
    expenses_total_text = ft.Text("₱0.00", weight=ft.FontWeight.BOLD)
    admin_expenses_total_text = ft.Text("₱0.00", weight=ft.FontWeight.BOLD)
    project_total_text = ft.Text("₱0.00", size=24, weight=ft.FontWeight.BOLD)

    def recalc_totals() -> None:
        materials_total = round(sum(r.total for r in material_rows), 2)
        labor_total = round(sum(r.total for r in labor_rows), 2)
        equipment_total = round(sum(r.total for r in equipment_rows), 2)
        expenses_total = round(sum(r.total for r in expense_rows), 2)
        admin_expenses_total = round(sum(r.total for r in admin_expense_rows), 2)
        materials_total_text.value = f"₱{materials_total:,.2f}"
        labor_total_text.value = f"₱{labor_total:,.2f}"
        equipment_total_text.value = f"₱{equipment_total:,.2f}"
        expenses_total_text.value = f"₱{expenses_total:,.2f}"
        admin_expenses_total_text.value = f"₱{admin_expenses_total:,.2f}"
        project_total_text.value = (
            f"₱{materials_total + labor_total + equipment_total + expenses_total + admin_expenses_total:,.2f}"
        )
        page.update()

    def refresh_materials_display() -> None:
        materials_column.controls.clear()
        groups: dict[tuple, list[MaterialRow]] = {}
        order: list[tuple] = []
        for row in material_rows:
            key = (row.dr_no, row.date, row.supplier)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)

        for key in order:
            rows_in_group = groups[key]
            dr_no, date, supplier = key
            group_total = round(sum(r.total for r in rows_in_group), 2)

            detail_controls = [
                ft.Container(
                    padding=ft.Padding.only(left=16),
                    content=ft.Row(
                        controls=[
                            ft.Text(row.name, expand=True),
                            ft.Text(f"{row.qty_number:g} {row.qty_unit}".strip(), width=100),
                            ft.Text(f"₱{row.total_price:,.2f}", width=110, text_align=ft.TextAlign.RIGHT),
                            row.delete_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
                for row in rows_in_group
            ]

            materials_column.controls.append(
                ft.ExpansionTile(
                    title=ft.Row(
                        controls=[
                            ft.Text(f"DR# {dr_no or '—'}", weight=ft.FontWeight.BOLD, width=130),
                            ft.Text(date or "—", width=100),
                            ft.Text(supplier or "—", expand=True),
                            ft.Text(f"₱{group_total:,.2f}", weight=ft.FontWeight.BOLD, width=110,
                                    text_align=ft.TextAlign.RIGHT),
                        ],
                    ),
                    controls=detail_controls,
                )
            )
        page.update()

    def add_material_row(dr_no: str = "", date: str = "", supplier: str = "", name: str = "",
                          qty_number: float = 0.0, qty_unit: str = "", total_price: float = 0.0) -> None:
        row = MaterialRow(on_delete=remove_material_row, dr_no=dr_no, date=date, supplier=supplier,
                           name=name, qty_number=qty_number, qty_unit=qty_unit, total_price=total_price)
        material_rows.append(row)

    def remove_material_row(row: MaterialRow) -> None:
        material_rows.remove(row)
        refresh_materials_display()
        recalc_totals()

    def refresh_labor_display() -> None:
        labor_column.controls.clear()
        groups: dict[tuple, list[LaborRow]] = {}
        order: list[tuple] = []
        for row in labor_rows:
            key = (row.payroll_no, row.date_start, row.date_end)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)

        for key in order:
            rows_in_group = groups[key]
            payroll_no, date_start, date_end = key
            group_total = round(sum(r.total for r in rows_in_group), 2)
            date_range_text = f"{date_start} to {date_end}" if date_start or date_end else "—"

            detail_controls = [
                ft.Container(
                    padding=ft.Padding.only(left=16),
                    content=ft.Row(
                        controls=[
                            ft.Text(row.worker, width=110),
                            ft.Text(row.skill, width=110),
                            ft.Text(f"₱{row.rate:,.2f}", width=90),
                            ft.Text(f"₱{row.cash_advance:,.2f}", width=100),
                            ft.Text(f"{row.overtime_hours:g}h (₱{row.overtime_pay:,.2f})", width=140),
                            ft.Text(row.days_display(), expand=True),
                            ft.Text(f"₱{row.total:,.2f}", width=110, weight=ft.FontWeight.BOLD,
                                    text_align=ft.TextAlign.RIGHT),
                            row.delete_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
                for row in rows_in_group
            ]

            labor_column.controls.append(
                ft.ExpansionTile(
                    title=ft.Row(
                        controls=[
                            ft.Text(f"Payroll# {payroll_no or '—'}", weight=ft.FontWeight.BOLD, width=140),
                            ft.Text(date_range_text, expand=True),
                            ft.Text(f"₱{group_total:,.2f}", weight=ft.FontWeight.BOLD, width=110,
                                    text_align=ft.TextAlign.RIGHT),
                        ],
                    ),
                    controls=detail_controls,
                )
            )
        page.update()

    def add_labor_row(payroll_no: str = "", date_start: str = "", date_end: str = "", worker: str = "",
                       skill: str = "", rate: float = 0.0, days_marked: Optional[list[str]] = None,
                       cash_advance: float = 0.0, overtime_hours: float = 0.0) -> None:
        row = LaborRow(on_delete=remove_labor_row, payroll_no=payroll_no, date_start=date_start,
                        date_end=date_end, worker=worker, skill=skill, rate=rate, days_marked=days_marked,
                        cash_advance=cash_advance, overtime_hours=overtime_hours)
        labor_rows.append(row)

    def remove_labor_row(row: LaborRow) -> None:
        labor_rows.remove(row)
        refresh_labor_display()
        recalc_totals()

    def add_equipment_row(equipment: str = "", days: str = "", rate: str = "") -> None:
        row = EquipmentRow(on_change=recalc_totals, on_delete=remove_equipment_row, equipment=equipment, days=days, rate=rate,)
        equipment_rows.append(row)
        equipment_column.controls.append(row.row)

    def remove_equipment_row(row: EquipmentRow) -> None:
        equipment_rows.remove(row)
        equipment_column.controls.remove(row.row)
        recalc_totals()

    def add_expense_row(receipt_no: str = "", date: str = "", paid_to: str = "",
                         description: str = "", amount: float = 0.0) -> None:
        row = ExpenseRow(on_delete=remove_expense_row, receipt_no=receipt_no, date=date,
                          paid_to=paid_to, description=description, amount=amount)
        expense_rows.append(row)
        expenses_column.controls.append(row.row)

    def remove_expense_row(row: ExpenseRow) -> None:
        expense_rows.remove(row)
        expenses_column.controls.remove(row.row)
        recalc_totals()

    def add_admin_expense_row(receipt_no: str = "", date: str = "", paid_to: str = "",
                               description: str = "", amount: float = 0.0) -> None:
        row = AdminExpenseRow(on_delete=remove_admin_expense_row, receipt_no=receipt_no, date=date,
                               paid_to=paid_to, description=description, amount=amount)
        admin_expense_rows.append(row)
        admin_expenses_column.controls.append(row.row)

    def remove_admin_expense_row(row: AdminExpenseRow) -> None:
        admin_expense_rows.remove(row)
        admin_expenses_column.controls.remove(row.row)
        recalc_totals()

    for m in project.materials:
        add_material_row(dr_no=m.dr_no, date=m.date, supplier=m.supplier, name=m.name,
                          qty_number=m.qty_number, qty_unit=m.qty_unit, total_price=m.total_price)
    refresh_materials_display()
    for l in project.labor:
        add_labor_row(payroll_no=l.payroll_no, date_start=l.date_start, date_end=l.date_end,
                      worker=l.worker, skill=l.skill, rate=l.rate, days_marked=l.days_marked,
                      cash_advance=l.cash_advance, overtime_hours=l.overtime_hours)
    refresh_labor_display()
    for e in project.equipment:
        add_equipment_row(equipment=e.equipment, days=f"{e.days:g}", rate=f"{e.rate:g}")
    for x in project.expenses:
        add_expense_row(receipt_no=x.receipt_no, date=x.date, paid_to=x.paid_to,
                         description=x.description, amount=x.amount)
    for x in project.admin_expenses:
        add_admin_expense_row(receipt_no=x.receipt_no, date=x.date, paid_to=x.paid_to,
                               description=x.description, amount=x.amount)

    def make_date_picker(label: str = "Date") -> dict:
        """A calendar-picker field matching the payroll date picker's ISO (YYYY-MM-DD) format."""
        info = {"value": ""}
        date_text = ft.Text("No date selected", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)

        def date_changed(e: ft.ControlEvent) -> None:
            if picker.value:
                info["value"] = picker.value.date().isoformat()
                date_text.value = info["value"]
                date_text.italic = False
                date_text.color = None
                page.update()

        picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1), last_date=datetime(2035, 12, 31),
            help_text=f"Select {label.lower()}", on_change=date_changed,
        )

        def open_picker(e: ft.ControlEvent) -> None:
            page.show_dialog(picker)

        row = ft.Row(
            controls=[
                ft.OutlinedButton(content=label, icon=ft.Icons.CALENDAR_MONTH, on_click=open_picker),
                date_text,
            ],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return {"row": row, "info": info}

    def open_material_modal(e: ft.ControlEvent) -> None:
        dr_no_field = ft.TextField(label="Dr. No", width=150)
        date_picker = make_date_picker()
        supplier_field = ft.TextField(label="Supplier Name", expand=True)

        modal_items: list[dict] = []
        items_column = ft.Column(spacing=8)
        modal_total_text = ft.Text("₱0.00", size=16, weight=ft.FontWeight.BOLD)

        def recalc_modal_total() -> None:
            total = sum(to_float(it["price_field"].value) for it in modal_items)
            modal_total_text.value = f"₱{total:,.2f}"
            page.update()

        def add_modal_item_row() -> None:
            name_field = ft.TextField(label="Material Name", expand=True, on_change=lambda e: recalc_modal_total())
            qty_number_field = ft.TextField(label="Qty", width=80, input_filter=NUMERIC_FILTER,
                                             keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: recalc_modal_total())
            qty_unit_field = ft.TextField(label="Unit", width=90, on_change=lambda e: recalc_modal_total())
            price_field = ft.TextField(label="Total Price", width=130, prefix="₱", input_filter=NUMERIC_FILTER,
                                        keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: recalc_modal_total())

            item = {"name_field": name_field, "qty_number_field": qty_number_field,
                    "qty_unit_field": qty_unit_field, "price_field": price_field}

            def remove_this_item(e: ft.ControlEvent) -> None:
                modal_items.remove(item)
                items_column.controls.remove(item["row"])
                recalc_modal_total()

            delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                           tooltip="Remove", on_click=remove_this_item)
            item["row"] = ft.Row(
                controls=[name_field, qty_number_field, qty_unit_field, price_field, delete_button],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            modal_items.append(item)
            items_column.controls.append(item["row"])
            page.update()

        def add_item_clicked(e: ft.ControlEvent) -> None:
            add_modal_item_row()

        def cancel_dr(e: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        def save_dr(e: ft.ControlEvent) -> None:
            dr_no = (dr_no_field.value or "").strip()
            date = date_picker["info"]["value"]
            supplier = (supplier_field.value or "").strip()
            for it in modal_items:
                name = (it["name_field"].value or "").strip()
                if not name:
                    continue
                add_material_row(
                    dr_no=dr_no, date=date, supplier=supplier, name=name,
                    qty_number=to_float(it["qty_number_field"].value),
                    qty_unit=(it["qty_unit_field"].value or "").strip(),
                    total_price=to_float(it["price_field"].value),
                )
            dialog.open = False
            refresh_materials_display()
            recalc_totals()

        add_modal_item_row()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Add Delivery Receipt"),
            content=ft.Container(
                width=650,
                content=ft.Column(
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        ft.Row(controls=[dr_no_field, date_picker["row"]]),
                        supplier_field,
                        ft.Divider(),
                        field_header([("Material Name", None), ("Qty", 80), ("Unit", 90), ("Total Price", 130)]),
                        items_column,
                        ft.TextButton(content="Add Item", icon=ft.Icons.ADD, on_click=add_item_clicked),
                        ft.Row(alignment=ft.MainAxisAlignment.END,
                               controls=[ft.Text("Total:", weight=ft.FontWeight.BOLD), modal_total_text]),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=cancel_dr),
                ft.ElevatedButton(content="Save", icon=ft.Icons.SAVE, on_click=save_dr),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def open_payroll_modal(e: ft.ControlEvent) -> None:
        payroll_no_field = ft.TextField(label="Payroll No.", width=180)
        date_range_text = ft.Text("No date range selected", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)

        period: dict = {"start": None, "end": None}
        row_states: list[dict] = []

        def period_dates() -> list:
            if not period["start"] or not period["end"]:
                return []
            days = (period["end"] - period["start"]).days
            return [period["start"] + timedelta(days=i) for i in range(days + 1)]

        def day_cell(d, row_state: dict) -> ft.Container:
            marked = d.isoformat() in row_state["marked"]

            def toggle(e: ft.ControlEvent) -> None:
                key = d.isoformat()
                if key in row_state["marked"]:
                    row_state["marked"].remove(key)
                else:
                    row_state["marked"].add(key)
                rebuild_cells(row_state)
                refresh_row_total(row_state)
                page.update()

            return ft.Container(
                width=34, height=34,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=4,
                alignment=ft.Alignment.CENTER,
                bgcolor=ft.Colors.GREEN_100 if marked else None,
                on_click=toggle,
                content=ft.Stack(
                    alignment=ft.Alignment.CENTER,
                    controls=[
                        ft.Text(str(d.day), size=12),
                        *([ft.Container(width=26, height=2, bgcolor=ft.Colors.RED_600, rotate=0.785)]
                          if marked else []),
                    ],
                ),
            )

        def rebuild_cells(row_state: dict) -> None:
            dates = period_dates()
            if not dates:
                row_state["cells_row"].controls = [
                    ft.Text("Select a date range above first", italic=True, size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT)
                ]
            else:
                row_state["cells_row"].controls = [day_cell(d, row_state) for d in dates]

        def refresh_row_total(row_state: dict) -> None:
            days = len(row_state["marked"])
            overtime_pay = (row_state["rate"] / 8) * row_state["overtime"]
            total = days * row_state["rate"] + overtime_pay - row_state["cash_advance"]
            row_state["total_text"].value = f"₱{total:,.2f}"

        def apply_period_change() -> None:
            if period["start"] and period["end"]:
                if period["end"] < period["start"]:
                    period["start"], period["end"] = period["end"], period["start"]
                date_range_text.value = f"{period['start'].isoformat()} to {period['end'].isoformat()}"
                for rs in row_states:
                    rs["marked"].clear()
                    rebuild_cells(rs)
                    refresh_row_total(rs)
            page.update()

        def start_date_changed(e: ft.ControlEvent) -> None:
            if start_date_picker.value:
                period["start"] = start_date_picker.value.date()
                apply_period_change()

        def end_date_changed(e: ft.ControlEvent) -> None:
            if end_date_picker.value:
                period["end"] = end_date_picker.value.date()
                apply_period_change()

        start_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1), last_date=datetime(2035, 12, 31),
            help_text="Select start date", on_change=start_date_changed,
        )
        end_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1), last_date=datetime(2035, 12, 31),
            help_text="Select end date", on_change=end_date_changed,
        )

        def open_start_date_picker(e: ft.ControlEvent) -> None:
            page.show_dialog(start_date_picker)

        def open_end_date_picker(e: ft.ControlEvent) -> None:
            page.show_dialog(end_date_picker)

        def create_row() -> dict:
            row_state: dict = {"marked": set(), "rate": 0.0, "skill": "", "cash_advance": 0.0, "overtime": 0.0}

            skill_text = ft.Text("—", width=110)
            rate_text = ft.Text("—", width=90)
            total_text = ft.Text("₱0.00", width=110, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT)
            cells_row = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=4)

            def cash_advance_changed(e: ft.ControlEvent) -> None:
                row_state["cash_advance"] = to_float(cash_advance_field.value)
                refresh_row_total(row_state)
                page.update()

            def overtime_changed(e: ft.ControlEvent) -> None:
                row_state["overtime"] = to_float(overtime_field.value)
                refresh_row_total(row_state)
                page.update()

            cash_advance_field = ft.TextField(label="Cash Advance", width=100, prefix="₱",
                                               input_filter=NUMERIC_FILTER, keyboard_type=ft.KeyboardType.NUMBER,
                                               on_change=cash_advance_changed)
            overtime_field = ft.TextField(label="OT Hours", width=100, input_filter=NUMERIC_FILTER,
                                           keyboard_type=ft.KeyboardType.NUMBER, on_change=overtime_changed)

            def worker_selected(e: ft.ControlEvent) -> None:
                info = WORKER_INFO.get(worker_dropdown.value)
                if info:
                    skill, rate = info
                    row_state["skill"] = skill
                    row_state["rate"] = rate
                    skill_text.value = skill
                    rate_text.value = f"₱{rate:,.2f}"
                else:
                    row_state["skill"] = ""
                    row_state["rate"] = 0.0
                    skill_text.value = "—"
                    rate_text.value = "—"
                refresh_row_total(row_state)
                page.update()

            worker_dropdown = ft.Dropdown(
                label="Worker", width=170,
                options=[ft.DropdownOption(key=name, text=f"{name} ({skill})") for name, skill, _ in WORKERS],
                on_select=worker_selected,
            )

            row_state.update({
                "worker_dropdown": worker_dropdown, "skill_text": skill_text, "rate_text": rate_text,
                "cash_advance_field": cash_advance_field, "overtime_field": overtime_field,
                "total_text": total_text, "cells_row": cells_row,
            })
            rebuild_cells(row_state)

            row_state["container"] = ft.Container(
                padding=ft.Padding.only(bottom=8),
                content=ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(controls=[worker_dropdown, skill_text, rate_text, cash_advance_field,
                                          overtime_field, total_text],
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Container(width=560, content=cells_row),
                    ],
                ),
            )
            return row_state

        for _ in range(PAYROLL_ROW_COUNT):
            row_states.append(create_row())

        def cancel_payroll(e: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        def save_payroll(e: ft.ControlEvent) -> None:
            payroll_no = (payroll_no_field.value or "").strip()
            date_start = period["start"].isoformat() if period["start"] else ""
            date_end = period["end"].isoformat() if period["end"] else ""
            for rs in row_states:
                worker = rs["worker_dropdown"].value or ""
                if not worker or not rs["marked"]:
                    continue
                add_labor_row(payroll_no=payroll_no, date_start=date_start, date_end=date_end,
                              worker=worker, skill=rs["skill"], rate=rs["rate"],
                              days_marked=sorted(rs["marked"]), cash_advance=rs["cash_advance"],
                              overtime_hours=rs["overtime"])
            dialog.open = False
            refresh_labor_display()
            recalc_totals()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Add Payroll"),
            content=ft.Container(
                width=900,
                padding=ft.Padding.all(16),
                content=ft.Column(
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        ft.Container(height=6),
                        ft.Row(controls=[
                            payroll_no_field,
                            ft.OutlinedButton(content="Start Date", icon=ft.Icons.CALENDAR_MONTH,
                                               on_click=open_start_date_picker),
                            ft.OutlinedButton(content="End Date", icon=ft.Icons.CALENDAR_MONTH,
                                               on_click=open_end_date_picker),
                        ]),
                        date_range_text,
                        ft.Divider(),
                        field_header([("Worker", 170), ("Skill", 110), ("Rate", 90),("Cash Advance", 100), ("Over Time", 100), ("Total", 110)]),
                        ft.Column(controls=[rs["container"] for rs in row_states], spacing=0),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=cancel_payroll),
                ft.ElevatedButton(content="Save", icon=ft.Icons.SAVE, on_click=save_payroll),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def add_equipment_clicked(e: ft.ControlEvent) -> None:
        add_equipment_row()
        page.update()

    def open_expense_style_modal(title: str, add_row: Callable[..., None]) -> None:
        receipt_no_field = ft.TextField(label="Receipt No.", width=150)
        date_picker = make_date_picker()
        paid_to_field = ft.TextField(label="Paid To", expand=True)

        modal_items: list[dict] = []
        items_column = ft.Column(spacing=8)
        modal_total_text = ft.Text("₱0.00", size=16, weight=ft.FontWeight.BOLD)

        def recalc_modal_total() -> None:
            total = sum(to_float(it["amount_field"].value) for it in modal_items)
            modal_total_text.value = f"₱{total:,.2f}"
            page.update()

        def add_modal_item_row() -> None:
            description_field = ft.TextField(label="Description", expand=True,
                                               on_change=lambda e: recalc_modal_total())
            amount_field = ft.TextField(label="Amount", width=140, prefix="₱", input_filter=NUMERIC_FILTER,
                                         keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: recalc_modal_total())
            item = {"description_field": description_field, "amount_field": amount_field}

            def remove_this_item(e: ft.ControlEvent) -> None:
                modal_items.remove(item)
                items_column.controls.remove(item["row"])
                recalc_modal_total()

            delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                           tooltip="Remove", on_click=remove_this_item)
            item["row"] = ft.Row(controls=[description_field, amount_field, delete_button],
                                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
            modal_items.append(item)
            items_column.controls.append(item["row"])
            page.update()

        def add_item_clicked(e: ft.ControlEvent) -> None:
            add_modal_item_row()

        def cancel_modal(e: ft.ControlEvent) -> None:
            dialog.open = False
            page.update()

        def save_modal(e: ft.ControlEvent) -> None:
            receipt_no = (receipt_no_field.value or "").strip()
            date = date_picker["info"]["value"]
            paid_to = (paid_to_field.value or "").strip()
            for it in modal_items:
                description = (it["description_field"].value or "").strip()
                if not description:
                    continue
                add_row(receipt_no=receipt_no, date=date, paid_to=paid_to,
                        description=description, amount=to_float(it["amount_field"].value))
            dialog.open = False
            recalc_totals()

        add_modal_item_row()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(
                width=650,
                content=ft.Column(
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        ft.Row(controls=[receipt_no_field, date_picker["row"]]),
                        paid_to_field,
                        ft.Divider(),
                        field_header([("Description", None), ("Amount", 140)]),
                        items_column,
                        ft.TextButton(content="Add Item", icon=ft.Icons.ADD, on_click=add_item_clicked),
                        ft.Row(alignment=ft.MainAxisAlignment.END,
                               controls=[ft.Text("Total:", weight=ft.FontWeight.BOLD), modal_total_text]),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(content="Cancel", on_click=cancel_modal),
                ft.ElevatedButton(content="Save", icon=ft.Icons.SAVE, on_click=save_modal),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def open_expense_modal(e: ft.ControlEvent) -> None:
        open_expense_style_modal("Add Expense", add_expense_row)

    def open_admin_expense_modal(e: ft.ControlEvent) -> None:
        open_expense_style_modal("Add Admin Expense", add_admin_expense_row)

    def save_clicked(e: ft.ControlEvent) -> None:
        name = (name_field.value or "").strip()
        if not name:
            name_field.error_text = "Project name is required"
            page.update()
            return
        name_field.error_text = None

        project.name = name
        project.description = (description_field.value or "").strip()
        project.location = (location_field.value or "").strip()
        project.budget = parse_amount(budget_field.value)
        project.materials = [r.to_item() for r in material_rows if r.has_content()]
        project.labor = [r.to_item() for r in labor_rows if r.has_content()]
        project.equipment = [r.to_item() for r in equipment_rows if r.has_content()]
        project.expenses = [r.to_item() for r in expense_rows if r.has_content()]
        project.admin_expenses = [r.to_item() for r in admin_expense_rows if r.has_content()]
        try:
            db.save_project(project)
        except ConnectionError as exc:
            notify(page, str(exc), error=True)
            return
        page.go("/")
        notify(page, f'Saved "{project.name}".')

    def cancel_clicked(e: ft.ControlEvent) -> None:
        page.go("/")

    recalc_totals()

    def field_header(labels_and_widths: list[tuple[str, Optional[int]]]) -> ft.Row:
        controls = []
        for label, width in labels_and_widths:
            controls.append(ft.Text(label, weight=ft.FontWeight.BOLD, width=width, expand=width is None))
        controls.append(ft.Container(width=40))
        return ft.Row(controls=controls)

    def tab_page(header: ft.Row, rows_column: ft.Column, add_label: str, add_clicked: Callable,
                 total_label: str, total_text: ft.Text) -> ft.Container:
        return ft.Container(
            padding=ft.Padding.only(top=8),
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=8,
                controls=[
                    header,
                    rows_column,
                    ft.TextButton(content=add_label, icon=ft.Icons.ADD, on_click=add_clicked),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        controls=[ft.Text(total_label, weight=ft.FontWeight.BOLD), total_text],
                    ),
                ],
            ),
        )

    tabs_control = ft.Tabs(
        length=5,
        content=ft.Column(
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="Material List", icon=ft.Icons.INVENTORY_2),
                        ft.Tab(label="Payroll", icon=ft.Icons.GROUPS),
                        ft.Tab(label="Equipment", icon=ft.Icons.CONSTRUCTION),
                        ft.Tab(label="Expense", icon=ft.Icons.MONEY),
                        ft.Tab(label="Admin Expense", icon=ft.Icons.GROUPS_2),
                    ],
                ),
                ft.Container(
                    height=380,
                    content=ft.TabBarView(
                        controls=[
                            tab_page(
                                field_header([("Delivery Receipt", 130), ("Date", 100), ("Supplier", None),
                                              ("Total", 110)]),
                                materials_column, "Add Material", open_material_modal,
                                "Materials Total:", materials_total_text,
                            ),
                            tab_page(
                                field_header([("Payroll No.", 140), ("Date Range", None), ("Total", 110)]),
                                labor_column, "Add Payroll", open_payroll_modal,
                                "Payroll Total:", labor_total_text,
                            ),
                            tab_page(
                                field_header([("Equipment", None), ("Days", 90), ("Rate", 120), ("Total", 100)]),
                                equipment_column, "Add Equipment", add_equipment_clicked,
                                "Equipment Total:", equipment_total_text,
                            ),
                            tab_page(
                                field_header([("Receipt No.", 100), ("Date", 100), ("Paid To", 140),
                                              ("Description", None), ("Amount", 120)]),
                                expenses_column, "Add Expense", open_expense_modal,
                                "Expenses Total:", expenses_total_text,
                            ),
                            tab_page(
                                field_header([("Receipt No.", 100), ("Date", 100), ("Paid To", 140),
                                              ("Description", None), ("Amount", 120)]),
                                admin_expenses_column, "Add Admin Expense", open_admin_expense_modal,
                                "Admin Expenses Total:", admin_expenses_total_text,
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )

    return ft.View(
        route=f"/project/edit/{project_id}" if project_id else "/project/new",
        appbar=ft.AppBar(
            leading=ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=cancel_clicked),
            title=ft.Text("Edit Project" if project_id else "New Project"),
        ),
        padding=ft.Padding.all(16),
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=750,
                        content=ft.Column(
                            spacing=12,
                            controls=[
                                name_field,
                                description_field,
                                ft.Row(controls=[location_field, budget_field]),
                                ft.Divider(),
                                tabs_control,
                                ft.Divider(),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.END,
                                    controls=[
                                        ft.OutlinedButton(content="Cancel", on_click=cancel_clicked),
                                        ft.ElevatedButton(content="Save Project", icon=ft.Icons.SAVE,
                                                           on_click=save_clicked),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
    )


def build_report_view(page: ft.Page, project_id: str) -> ft.View:
    project = db.get_project(project_id)
    if project is None:
        return build_not_found_view(page, f"/project/report/{project_id}")
    file_picker = ft.FilePicker()

    def back_clicked(e: ft.ControlEvent) -> None:
        page.go("/")

    async def export_pdf_clicked(e: ft.ControlEvent) -> None:
        await export_project_report(page, file_picker, project, "pdf")

    async def export_docx_clicked(e: ft.ControlEvent) -> None:
        await export_project_report(page, file_picker, project, "docx")

    async def export_csv_clicked(e: ft.ControlEvent) -> None:
        await export_project_report(page, file_picker, project, "csv")

    def materials_table() -> ft.Control:
        if not project.materials:
            return ft.Text("No material line items.", color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Dr. No")),
                ft.DataColumn(ft.Text("Date")),
                ft.DataColumn(ft.Text("Supplier")),
                ft.DataColumn(ft.Text("Item")),
                ft.DataColumn(ft.Text("Qty"), numeric=True),
                ft.DataColumn(ft.Text("Total"), numeric=True),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(m.dr_no)),
                    ft.DataCell(ft.Text(m.date)),
                    ft.DataCell(ft.Text(m.supplier)),
                    ft.DataCell(ft.Text(m.name)),
                    ft.DataCell(ft.Text(f"{m.qty_number:g} {m.qty_unit}".strip())),
                    ft.DataCell(ft.Text(f"₱{m.total:,.2f}")),
                ])
                for m in project.materials
            ],
        )

    def labor_table() -> ft.Control:
        if not project.labor:
            return ft.Text("No labor line items.", color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Name")),
                ft.DataColumn(ft.Text("Skill")),
                ft.DataColumn(ft.Text("Rate"), numeric=True),
                ft.DataColumn(ft.Text("Days"), numeric=True),
                ft.DataColumn(ft.Text("CA"), numeric=True),
                ft.DataColumn(ft.Text("OT"), numeric=True),
                ft.DataColumn(ft.Text("Total"), numeric=True),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(l.worker)),
                    ft.DataCell(ft.Text(l.skill)),
                    ft.DataCell(ft.Text(f"₱{l.rate:,.2f}")),
                    ft.DataCell(ft.Text(f"{l.days:g}")),
                    ft.DataCell(ft.Text(f"₱{l.cash_advance:,.2f}")),
                    ft.DataCell(ft.Text(f"₱{l.overtime_pay:,.2f}")),
                    ft.DataCell(ft.Text(f"₱{l.total:,.2f}")),
                ])
                for l in project.labor
            ],
        )

    def equipment_table() -> ft.Control:
        if not project.equipment:
            return ft.Text("No Equipment line items.", color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.DataTable(
            columns = [
                ft.DataColumn(ft.Text("Equipment")),
                ft.DataColumn(ft.Text("Days"), numeric=True),
                ft.DataColumn(ft.Text("Rate"), numeric=True),
                ft.DataColumn(ft.Text("Total"), numeric=True),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(e.equipment)),
                    ft.DataCell(ft.Text(f"{e.days:g}")),
                    ft.DataCell(ft.Text(f"₱{e.rate:,.2f}")),
                    ft.DataCell(ft.Text(f"₱{e.total:,.2f}")),
                ])
                for e in project.equipment
            ]
        )

    def expenses_table() -> ft.Control:
        if not project.expenses:
            return ft.Text("No expense line items.", color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Receipt No.")),
                ft.DataColumn(ft.Text("Date")),
                ft.DataColumn(ft.Text("Paid To")),
                ft.DataColumn(ft.Text("Description")),
                ft.DataColumn(ft.Text("Amount"), numeric=True),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(x.receipt_no)),
                    ft.DataCell(ft.Text(x.date)),
                    ft.DataCell(ft.Text(x.paid_to)),
                    ft.DataCell(ft.Text(x.description)),
                    ft.DataCell(ft.Text(f"₱{x.amount:,.2f}")),
                ])
                for x in project.expenses
            ],
        )

    def admin_expenses_table() -> ft.Control:
        if not project.admin_expenses:
            return ft.Text("No admin expense line items.", color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Receipt No.")),
                ft.DataColumn(ft.Text("Date")),
                ft.DataColumn(ft.Text("Paid To")),
                ft.DataColumn(ft.Text("Description")),
                ft.DataColumn(ft.Text("Amount"), numeric=True),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(x.receipt_no)),
                    ft.DataCell(ft.Text(x.date)),
                    ft.DataCell(ft.Text(x.paid_to)),
                    ft.DataCell(ft.Text(x.description)),
                    ft.DataCell(ft.Text(f"₱{x.amount:,.2f}")),
                ])
                for x in project.admin_expenses
            ],
        )

    return ft.View(
        route=f"/project/report/{project_id}",
        appbar=ft.AppBar(
            leading=ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=back_clicked),
            title=ft.Text(f"Cost Report — {project.name}"),
        ),
        padding=ft.Padding.all(16),
        services=[file_picker],
        controls=[
            ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    *([ft.Text(project.description, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)]
                      if project.description else []),
                    *([ft.Text(
                        "   ·   ".join(filter(None, [
                            f"Location: {project.location}" if project.location else "",
                            f"Budget: ₱{project.budget:,.2f}" if project.budget else "",
                        ])),
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    )] if project.location or project.budget else []),
                    ft.Row(
                        controls=[
                            ft.ElevatedButton(content="Export PDF", icon=ft.Icons.PICTURE_AS_PDF,
                                               on_click=export_pdf_clicked),
                            ft.ElevatedButton(content="Export Word", icon=ft.Icons.DESCRIPTION,
                                               on_click=export_docx_clicked),
                            ft.ElevatedButton(content="Export CSV", icon=ft.Icons.TABLE_CHART,
                                               on_click=export_csv_clicked),
                        ],
                    ),
                    ft.Divider(),
                    ft.Text("Materials", size=16, weight=ft.FontWeight.W_500),
                    materials_table(),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Materials Total:", weight=ft.FontWeight.BOLD),
                                     ft.Text(f"₱{project.materials_total:,.2f}", weight=ft.FontWeight.BOLD)]),
                    ft.Divider(),
                    ft.Text("Labor", size=16, weight=ft.FontWeight.W_500),
                    labor_table(),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Labor Total:", weight=ft.FontWeight.BOLD),
                                     ft.Text(f"₱{project.labor_total:,.2f}", weight=ft.FontWeight.BOLD)]),
                    ft.Divider(),
                    ft.Text("Equipment", size=16, weight=ft.FontWeight.W_500),
                    equipment_table(),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Equipment Total:", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"₱{project.equipment_total:,.2f}", weight=ft.FontWeight.BOLD)]),
                    ft.Divider(),
                    ft.Text("Expenses", size=16, weight=ft.FontWeight.W_500),
                    expenses_table(),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Expenses Total:", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"₱{project.expenses_total:,.2f}", weight=ft.FontWeight.BOLD)]),
                    ft.Divider(),
                    ft.Text("Admin Expenses", size=16, weight=ft.FontWeight.W_500),
                    admin_expenses_table(),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Admin Expenses Total:", weight=ft.FontWeight.BOLD),
                                    ft.Text(f"₱{project.admin_expenses_total:,.2f}", weight=ft.FontWeight.BOLD)]),
                    ft.Row(alignment=ft.MainAxisAlignment.END,
                           controls=[ft.Text("Project Cost:", size=24),
                                     ft.Text(f"₱{project.total_cost:,.2f}",
                                             size=24,
                                             weight=ft.FontWeight.BOLD)]),
                ],
            ),
        ],
    )


def main(page: ft.Page) -> None:
    page.title = "Construction Project Manager"
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE_GREY)
    page.window.width = 1100
    page.window.height = 900
    page.window.min_width = 600
    page.window.min_height = 500

    try:
        db.init_db()
    except ConnectionError as exc:
        page.add(
            ft.Container(
                padding=ft.Padding.all(54),
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.CLOUD_OFF, size=64, color=ft.Colors.ERROR),
                        ft.Text("Can't reach the database", size=22),
                        ft.Container(
                            padding=ft.Padding(left=60, right=60, top=0, bottom=0),
                            content=ft.Text(str(exc), text_align=ft.TextAlign.CENTER),
                        ),
                    ],
                ),
            )
        )
        return

    def route_change(e: ft.RouteChangeEvent) -> None:
        page.views.clear()
        page.views.append(build_list_view(page))

        route = ft.TemplateRoute(page.route)
        if route.match("/project/new"):
            page.views.append(build_edit_view(page, None))
        elif route.match("/project/edit/:id"):
            page.views.append(build_edit_view(page, route.id))
        elif route.match("/project/report/:id"):
            page.views.append(build_report_view(page, route.id))

        page.update()

    def view_pop(e: ft.ViewPopEvent) -> None:
        page.views.pop()
        page.go(page.views[-1].route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    try:
        if not db.list_projects():
            page.route = "/project/new"
    except ConnectionError:
        pass
    route_change(None)


if __name__ == "__main__":
    ft.run(main)
