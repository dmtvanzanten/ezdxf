# Copyright (c) 2019-2022, Manfred Moitzi
# License: MIT License
from typing import TYPE_CHECKING, Optional, Tuple, cast, Dict
import logging
from dataclasses import dataclass
from ezdxf.lldxf import validator
from ezdxf.lldxf.attributes import (
    DXFAttr,
    DXFAttributes,
    DefSubclass,
    RETURN_DEFAULT,
    group_code_mapping,
)
from ezdxf import colors as clr
from ezdxf.lldxf.const import (
    DXF12,
    SUBCLASS_MARKER,
    DXF2000,
    DXF2007,
    DXF2004,
    INVALID_NAME_CHARACTERS,
    DXFValueError,
    LINEWEIGHT_BYBLOCK,
    LINEWEIGHT_BYLAYER,
    LINEWEIGHT_DEFAULT,
)
from ezdxf.entities.dxfentity import base_class, SubclassProcessor, DXFEntity
from .factory import register_entity

logger = logging.getLogger("ezdxf")

if TYPE_CHECKING:
    from ezdxf.eztypes import TagWriter, DXFNamespace, Viewport

__all__ = ["Layer", "acdb_symbol_table_record", "ViewportOverrides"]


def is_valid_layer_color_index(aci: int) -> bool:
    # BYBLOCK or BYLAYER is not valid a layer color!
    return (-256 < aci < 256) and aci != 0


def fix_layer_color(aci: int) -> int:
    return aci if is_valid_layer_color_index(aci) else 7


def is_valid_layer_lineweight(lw: int) -> bool:
    if validator.is_valid_lineweight(lw):
        if lw not in (LINEWEIGHT_BYLAYER, LINEWEIGHT_BYBLOCK):
            return True
    return False


def fix_layer_lineweight(lw: int) -> int:
    if lw in (LINEWEIGHT_BYLAYER, LINEWEIGHT_BYBLOCK):
        return LINEWEIGHT_DEFAULT
    else:
        return validator.fix_lineweight(lw)


acdb_symbol_table_record: DefSubclass = DefSubclass("AcDbSymbolTableRecord", {})

acdb_layer_table_record = DefSubclass(
    "AcDbLayerTableRecord",
    {
        # Layer name as string
        "name": DXFAttr(2, validator=validator.is_valid_layer_name),
        "flags": DXFAttr(70, default=0),
        # ACI color index, color < 0 indicates layer status: off
        "color": DXFAttr(
            62,
            default=7,
            validator=is_valid_layer_color_index,
            fixer=fix_layer_color,
        ),
        # True color as 24 bit int value: 0x00RRGGBB
        "true_color": DXFAttr(420, dxfversion=DXF2004, optional=True),
        # Linetype name as string
        "linetype": DXFAttr(
            6, default="Continuous", validator=validator.is_valid_table_name
        ),
        # 0 = don't plot layer; 1 = plot layer
        "plot": DXFAttr(
            290,
            default=1,
            dxfversion=DXF2000,
            optional=True,
            validator=validator.is_integer_bool,
            fixer=RETURN_DEFAULT,
        ),
        # Default lineweight 1/100 mm, min 0 = 0.0mm, max 211 = 2.11mm
        "lineweight": DXFAttr(
            370,
            default=LINEWEIGHT_DEFAULT,
            dxfversion=DXF2000,
            validator=is_valid_layer_lineweight,
            fixer=fix_layer_lineweight,
        ),
        # Handle to PlotStyleName, group code 390 is required by AutoCAD
        "plotstyle_handle": DXFAttr(390, dxfversion=DXF2000),
        # Handle to Material object
        "material_handle": DXFAttr(347, dxfversion=DXF2007),
        # Handle to ???
        "unknown1": DXFAttr(348, dxfversion=DXF2007, optional=True),
    },
)
acdb_layer_table_record_group_codes = group_code_mapping(
    acdb_layer_table_record
)
AcAecLayerStandard = "AcAecLayerStandard"
AcCmTransparency = "AcCmTransparency"


@register_entity
class Layer(DXFEntity):
    """DXF LAYER entity"""

    DXFTYPE = "LAYER"
    DXFATTRIBS = DXFAttributes(
        base_class, acdb_symbol_table_record, acdb_layer_table_record
    )
    DEFAULT_ATTRIBS = {"name": "0"}
    FROZEN = 0b00000001
    THAW = 0b11111110
    LOCK = 0b00000100
    UNLOCK = 0b11111011

    def load_dxf_attribs(
        self, processor: SubclassProcessor = None
    ) -> "DXFNamespace":
        dxf = super().load_dxf_attribs(processor)
        if processor:
            processor.simple_dxfattribs_loader(
                dxf, acdb_layer_table_record_group_codes  # type: ignore
            )
        return dxf

    def export_entity(self, tagwriter: "TagWriter") -> None:
        super().export_entity(tagwriter)
        if tagwriter.dxfversion > DXF12:
            tagwriter.write_tag2(SUBCLASS_MARKER, acdb_symbol_table_record.name)
            tagwriter.write_tag2(SUBCLASS_MARKER, acdb_layer_table_record.name)

        self.dxf.export_dxf_attribs(
            tagwriter,
            [
                "name",
                "flags",
                "color",
                "true_color",
                "linetype",
                "plot",
                "lineweight",
                "plotstyle_handle",
                "material_handle",
                "unknown1",
            ],
        )

    def set_required_attributes(self):
        if not self.dxf.hasattr("material"):
            global_ = self.doc.materials["Global"]
            if isinstance(global_, DXFEntity):
                handle = global_.dxf.handle
            else:
                handle = global_
            self.dxf.material_handle = handle
        if not self.dxf.hasattr("plotstyle_handle"):
            normal = self.doc.plotstyles["Normal"]
            if isinstance(normal, DXFEntity):
                handle = normal.dxf.handle
            else:
                handle = normal
            self.dxf.plotstyle_handle = handle

    def is_frozen(self) -> bool:
        """Returns ``True`` if layer is frozen."""
        return self.dxf.flags & Layer.FROZEN > 0

    def freeze(self) -> None:
        """Freeze layer."""
        self.dxf.flags = self.dxf.flags | Layer.FROZEN

    def thaw(self) -> None:
        """Thaw layer."""
        self.dxf.flags = self.dxf.flags & Layer.THAW

    def is_locked(self) -> bool:
        """Returns ``True`` if layer is locked."""
        return self.dxf.flags & Layer.LOCK > 0

    def lock(self) -> None:
        """Lock layer, entities on this layer are not editable - just important
        in CAD applications.
        """
        self.dxf.flags = self.dxf.flags | Layer.LOCK

    def unlock(self) -> None:
        """Unlock layer, entities on this layer are editable - just important
        in CAD applications.
        """
        self.dxf.flags = self.dxf.flags & Layer.UNLOCK

    def is_off(self) -> bool:
        """Returns ``True`` if layer is off."""
        return self.dxf.color < 0

    def is_on(self) -> bool:
        """Returns ``True`` if layer is on."""
        return not self.is_off()

    def on(self) -> None:
        """Switch layer `on` (visible)."""
        self.dxf.color = abs(self.dxf.color)

    def off(self) -> None:
        """Switch layer `off` (invisible)."""
        self.dxf.color = -abs(self.dxf.color)

    def get_color(self) -> int:
        """Get layer color, safe method for getting the layer color, because
        dxf.color is negative for layer status `off`.
        """
        return abs(self.dxf.color)

    def set_color(self, color: int) -> None:
        """Set layer color, safe method for setting the layer color, because
        dxf.color is negative for layer status `off`.
        """
        color = abs(color) if self.is_on() else -abs(color)
        self.dxf.color = color

    @property
    def rgb(self) -> Optional[Tuple[int, int, int]]:
        """Returns RGB true color as (r, g, b)-tuple or None if attribute
        dxf.true_color is not set.
        """
        if self.dxf.hasattr("true_color"):
            return clr.int2rgb(self.dxf.get("true_color"))
        else:
            return None

    @rgb.setter
    def rgb(self, rgb: Tuple[int, int, int]) -> None:
        """Set RGB true color as (r, g, b)-tuple e.g. (12, 34, 56)."""
        self.dxf.set("true_color", clr.rgb2int(rgb))

    @property
    def color(self) -> int:
        """Get layer color, safe method for getting the layer color, because
        dxf.color is negative for layer status `off`.
        """
        return self.get_color()

    @color.setter
    def color(self, value: int) -> None:
        """Set layer color, safe method for setting the layer color, because
        dxf.color is negative for layer status `off`.
        """
        self.set_color(value)

    @property
    def description(self) -> str:
        try:
            xdata = self.get_xdata(AcAecLayerStandard)
        except DXFValueError:
            return ""
        else:
            if len(xdata) > 1:
                # this is the usual case in BricsCAD
                return xdata[1].value
            else:
                return ""

    @description.setter
    def description(self, value: str) -> None:
        # create AppID table entry if not present
        if self.doc and AcAecLayerStandard not in self.doc.appids:
            self.doc.appids.new(AcAecLayerStandard)
        self.discard_xdata(AcAecLayerStandard)
        self.set_xdata(AcAecLayerStandard, [(1000, ""), (1000, value)])

    @property
    def transparency(self) -> float:
        try:
            xdata = self.get_xdata(AcCmTransparency)
        except DXFValueError:
            return 0.0
        else:
            t = xdata[0].value
            if t & 0x2000000:  # is this a real transparency value?
                # Transparency BYBLOCK (0x01000000) make no sense for a layer!?
                return clr.transparency2float(t)
        return 0.0

    @transparency.setter
    def transparency(self, value: float) -> None:
        # create AppID table entry if not present
        if self.doc and AcCmTransparency not in self.doc.appids:
            self.doc.appids.new(AcCmTransparency)
        if 0 <= value <= 1:
            self.discard_xdata(AcCmTransparency)
            self.set_xdata(
                AcCmTransparency, [(1071, clr.float2transparency(value))]
            )
        else:
            raise ValueError("Value out of range (0 .. 1).")

    def rename(self, name: str) -> None:
        """
        Rename layer and all known (documented) references to this layer.

        .. warning::

            Renaming layers may damage the DXF file in some circumstances!

        Args:
             name: new layer name

        Raises:
            ValueError: `name` contains invalid characters: <>/\\":;?*|=`
            ValueError: layer `name` already exist
            ValueError: renaming of layers ``'0'`` and ``'DEFPOINTS'`` not
                possible

        """
        if not validator.is_valid_layer_name(name):
            raise ValueError(
                f"Name contains invalid characters: {INVALID_NAME_CHARACTERS}."
            )
        assert self.doc is not None, "valid DXF document is required"
        layers = self.doc.layers
        if self.dxf.name.lower() in ("0", "defpoints"):
            raise ValueError(f'Can not rename layer "{self.dxf.name}".')
        if layers.has_entry(name):
            raise ValueError(f'Layer "{name}" already exist.')
        old = self.dxf.name
        self.dxf.name = name
        layers.replace(old, self)
        self._rename_layer_references(old, name)

    def _rename_layer_references(self, old_name: str, new_name: str) -> None:
        assert self.doc is not None, "valid DXF document is required"
        key = self.doc.layers.key
        old_key = key(old_name)
        for e in self.doc.entitydb.values():
            if e.dxf.hasattr("layer") and key(e.dxf.layer) == old_key:
                e.dxf.layer = new_name
            entity_type = e.dxftype()
            if entity_type == "VIEWPORT":
                e.rename_frozen_layer(old_name, new_name)
            elif entity_type == "LAYER_FILTER":
                # todo: if LAYER_FILTER implemented, add support for
                #  renaming layers
                logger.debug(
                    f'renaming layer "{old_name}" - document contains '
                    f"LAYER_FILTER"
                )
            elif entity_type == "LAYER_INDEX":
                # todo: if LAYER_INDEX implemented, add support for
                #  renaming layers
                logger.debug(
                    f'renaming layer "{old_name}" - document contains '
                    f"LAYER_INDEX"
                )

    def get_vp_overrides(self) -> "ViewportOverrides":
        """Returns the :class:`ViewportOverrides` object of this layer."""
        return ViewportOverrides(self)


@dataclass
class OverrideAttributes:
    aci: int
    rgb: Optional[clr.RGB]
    transparency: float
    linetype: str
    lineweight: int
    frozen: bool


class ViewportOverrides:
    def __init__(self, layer: Layer):
        assert layer.doc is not None, "valid DXF document required"
        self._layer = layer
        self._overrides = load_layer_overrides(layer)

    def has_overrides(self, vp_handle: str = None) -> bool:
        """Returns ``True`` if any overrides exist for the given VIEWPORT
        handle. Returns ``True`` if any overrides exist if no handle is given.
        """
        if vp_handle is None:
            return bool(self._overrides)
        return vp_handle in self._overrides

    def default_settings(self, frozen: bool) -> OverrideAttributes:
        """Returns the default settings of the layer."""
        layer = self._layer
        return OverrideAttributes(
            aci=layer.color,
            rgb=layer.rgb,
            transparency=layer.transparency,
            linetype=layer.dxf.linetype,
            lineweight=layer.dxf.lineweight,
            frozen=frozen,
        )

    def commit(self) -> None:
        """Write VIEWPORT overrides back into the extension dictionary of the
        layer. Without a commit() all changes are lost!
        """
        store_layer_overrides(self._layer, self._overrides)

    def _acquire_overrides(self, vp_handle: str) -> OverrideAttributes:
        """Returns the OverrideAttributes() instance for `vp_handle`, creates a new
        OverrideAttributes() instance if none exist.
        """
        return self._overrides.setdefault(
            vp_handle,
            self.default_settings(
                is_layer_frozen_in_vp(self._layer, vp_handle)
            ),
        )

    def _get_overrides(self, vp_handle: str) -> OverrideAttributes:
        """Returns the overrides for `vp_handle`, returns the default layer
        settings if no Override() instance exist.
        """
        try:
            return self._overrides[vp_handle]
        except KeyError:
            return self.default_settings(
                is_layer_frozen_in_vp(self._layer, vp_handle)
            )

    def set_color(self, vp_handle: str, value: int) -> None:
        """Override the :ref:`ACI`."""
        # BYBLOCK or BYLAYER is not valid a layer color
        if not is_valid_layer_color_index(value):
            raise ValueError(f"invalid ACI value: {value}")
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.aci = value

    def get_color(self, vp_handle: str) -> int:
        """Returns the :ref:`ACI` override or the original layer value if no
        override exist.
        """
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.aci

    def set_rgb(self, vp_handle: str, value: Optional[clr.RGB]):
        """Set the RGB override as (red, gree, blue) tuple or ``None`` to remove
        the true color setting.

        """
        if value is not None and not validator.is_valid_rgb(value):
            raise ValueError(f"invalid RGB value: {value}")
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.rgb = value

    def get_rgb(self, vp_handle: str) -> Optional[clr.RGB]:
        """Returns the RGB override or the original layer value if no
        override exist. Returns ``None`` if no true color value is set.
        """
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.rgb

    def set_transparency(self, vp_handle: str, value: float) -> None:
        """Set the transparency override. A transparency of 0 is opaque and 1
        is fully transparent.
        """
        if not (0.0 <= value <= 1.0):
            raise ValueError(
                f"invalid transparency: {value}, has to be in the range [0, 1]"
            )
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.transparency = value

    def get_transparency(self, vp_handle: str) -> float:
        """Returns the transparency override or the original layer value if no
        override exist. Returns 0 for opaque and 1 for fully transparent.
        """
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.transparency

    def set_linetype(self, vp_handle: str, value: str) -> None:
        """Set the linetype override."""
        if value not in self._layer.doc.linetypes:  # type: ignore
            raise ValueError(
                f"invalid linetype: {value}, a linetype table entry is required"
            )
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.linetype = value

    def get_linetype(self, vp_handle: str) -> str:
        """Returns the linetype override or the original layer value if no
        override exist.
        """
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.linetype

    def get_lineweight(self, vp_handle: str) -> int:
        """Returns the lineweight override or the original layer value if no
        override exist.
        """
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.lineweight

    def set_lineweight(self, vp_handle: str, value: int) -> None:
        """Set the lineweight override."""
        if not is_valid_layer_lineweight(value):
            raise ValueError(
                f"invalid lineweight: {value}, a linetype table entry is required"
            )
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.lineweight = value

    def is_frozen(self, vp_handle: str) -> bool:
        """Returns ``True`` if layer is frozen in VIEWPORT `vp_handle`."""
        vp_overrides = self._get_overrides(vp_handle)
        return vp_overrides.frozen

    def freeze(self, vp_handle) -> None:
        """Freeze layer in given VIEWPORT."""
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.frozen = True

    def thaw(self, vp_handle) -> None:
        """Thaw layer in given VIEWPORT."""
        vp_overrides = self._acquire_overrides(vp_handle)
        vp_overrides.frozen = False


def is_layer_frozen_in_vp(layer, vp_handle) -> bool:
    """Returns ``True`` if layer is frozen in VIEWPORT defined by the vp_handle."""
    vp = cast("Viewport", layer.doc.entitydb.get(vp_handle))
    if vp is not None:
        return layer.dxf.name in vp.frozen_layers
    return False


def load_layer_overrides(layer: Layer) -> Dict[str, OverrideAttributes]:
    """Load all VIEWPORT overrides from the layer extension dictionary."""
    return dict()


def store_layer_overrides(
    layer: Layer, overrides: Dict[str, OverrideAttributes]
) -> None:
    """Store all VIEWPORT overrides in the layer extension dictionary.
    Replaces all existing overrides!
    """
    pass
