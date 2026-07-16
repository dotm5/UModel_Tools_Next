# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# pylint: skip-file
# pep8: noqa
#
# Inlined from the Blender PSK/PSA importer by Darknet, flufy3d, camg188, befzz.
# Source project: https://github.com/Befzz/blender3d_import_psk_psa
# Only the PSK/PSKX import implementation used by UModel Tools Next is retained here.

"""
Version': '2.0' ported by Darknet

Unreal Tournament PSK file to Blender mesh converter V1.0
Author: D.M. Sturgeon (camg188 at the elYsium forum), ported by Darknet
Imports a *psk file to a new mesh

-No UV Texutre
-No Weight
-No Armature Bones
-No Material ID
-Export Text Log From Current Location File (Bool )
"""

"""
Version': '2.7.*' edited by befzz
Github: https://github.com/Befzz/blender3d_import_psk_psa
- Pskx support
- Animation import updated (bone orientation now works)
- Skeleton import: auto-size, auto-orient bones
- UVmap, mesh, weights, etc. import revised
- Extra UVs import

- No Scale support. (no test material)
- No smoothing groups (not exported by umodel)
"""

"""
Version': '2.8.0' edited by floxay
- Vertex normals import (VTXNORMS chunk)
        (requires custom UEViewer build /at the moment/)
"""

# https://github.com/gildor2/UModel/blob/master/Exporters/Psk.h

import bpy
import re
from mathutils import Vector, Matrix, Quaternion

from struct import unpack, unpack_from, Struct
import time


def normalize_ue_name(value, fallback="Unnamed"):
    if isinstance(value, bytes):
        name = value.decode("utf-8", errors="replace")
    elif value is None:
        name = fallback
    else:
        name = str(value)

    name = name.replace("\x00", "").strip()
    return name if name else fallback


def configure_mesh_normals(mesh_data, normals):
    if normals is None:
        return

    if len(normals) != len(mesh_data.vertices):
        raise ValueError(
            "PSK custom normal count does not match mesh vertex count: "
            f"{len(normals)} normals for {len(mesh_data.vertices)} vertices."
        )

    mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
    mesh_data.normals_split_custom_set_from_vertices(normals)

    if hasattr(mesh_data, "use_auto_smooth"):
        mesh_data.use_auto_smooth = True

    mesh_data.update()

#DEV
# from mathutils import *
# from math import *


def util_obj_link(context, obj):
    # return bpy.context.scene_collection.objects.link(obj)
    # bpy.context.view_layer.collections[0].collection.objects.link(obj)
    # return bpy.context.collection.objects.link(obj)
    # bpy.data.scenes[0].collection.objects.link(obj)
    context.collection.objects.link(obj)

def util_obj_select(context, obj, action = 'SELECT'):
    # if obj.name in bpy.data.scenes[0].view_layers[0].objects:
    if obj.name in context.view_layer.objects:
        return obj.select_set(action == 'SELECT')
    else:
        print('Warning: util_obj_select: Object not in "context.view_layer.objects"')

def util_obj_set_active(context, obj):
    # bpy.context.view_layer.objects.active = obj
    # bpy.data.scenes[0].view_layers[0].objects.active = obj
    context.view_layer.objects.active = obj

def util_get_scene(context):
    return context.scene

def get_uv_layers(mesh_obj):
    return mesh_obj.uv_layers

def obj_select_get(obj):
    return obj.select_get()


def utils_set_mode(mode):
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode = mode, toggle = False)
    # else:
        # bpy.ops.object.mode_set(mode = mode, toggle = False)
        #dev

# since names have type ANSICHAR(signed char) - using cp1251(or 'ASCII'?)
def util_bytes_to_str(in_bytes):
    return in_bytes.rstrip(b'\x00').decode(encoding = 'cp1252', errors = 'replace')

class class_psk_bone:
    name = ""

    parent = None

    bone_index = 0
    parent_index = 0

    # scale = []

    mat_world = None
    mat_world_rot = None

    orig_quat = None
    orig_loc = None

    children = None

    have_weight_data = False

# TODO simplify?
def util_select_all(select):
    if select:
        actionString = 'SELECT'
    else:
        actionString = 'DESELECT'

    if bpy.ops.object.select_all.poll():
        bpy.ops.object.select_all(action = actionString)

    if bpy.ops.mesh.select_all.poll():
        bpy.ops.mesh.select_all(action = actionString)

    if bpy.ops.pose.select_all.poll():
        bpy.ops.pose.select_all(action = actionString)


def util_ui_show_msg(msg):
    bpy.ops.pskpsa.message('INVOKE_DEFAULT', message = msg)


PSKPSA_FILE_HEADER = {
    'psk':b'ACTRHEAD\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
    'psa':b'ANIMHEAD\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
}


def util_is_header_valid(filename, file_ext, chunk_id, error_callback):
    '''Return True if chunk_id is a valid psk/psa (file_ext) 'magick number'.'''
    if chunk_id != PSKPSA_FILE_HEADER[file_ext]:
        error_callback(
            "File %s is not a %s file. (header mismach)\nExpected: %s \nPresent %s"  % (
                filename, file_ext,
                PSKPSA_FILE_HEADER[file_ext], chunk_id)
        )
        return False
    return True


def util_gen_name_part(filepath):
    '''Return file name without extension'''
    return re.match(r'.*[/\\]([^/\\]+?)(\..{2,5})?$', filepath).group(1)


def vec_to_axis_vec(vec_in, vec_out):
    '''Make **vec_out** to be an axis-aligned unit vector that is closest to vec_in. (basis?)'''
    x, y, z = vec_in
    if abs(x) > abs(y):
        if abs(x) > abs(z):
            vec_out.x = 1 if x >= 0 else -1
        else:
            vec_out.z = 1 if z >= 0 else -1
    else:
        if abs(y) > abs(z):
            vec_out.y = 1 if y >= 0 else -1
        else:
            vec_out.z = 1 if z >= 0 else -1


def calc_bone_rotation(psk_bone, bone_len, bDirectly, avg_bone_len):
    children = psk_bone.children

    vecy = Vector((0.0, 1.0, 0.0))
    quat = Quaternion((1.0, 0.0, 0.0, 0.0))
    axis_vec = Vector()

    # bone with 0 children (orphan bone)
    if len(children) == 0:
        # Single bone. ALONE.
        if psk_bone.parent == None:
            return (bone_len, quat)

        elif bDirectly:
                        # @
            # axis_vec = psk_bone.orig_quat * psk_bone.orig_loc
            axis_vec = psk_bone.orig_loc.copy()
            axis_vec.rotate( psk_bone.orig_quat )

        else:
            # bone Head near parent Head?
            if psk_bone.orig_loc.length < 0.1 * avg_bone_len:
                # @
                # vec_to_axis_vec(psk_bone.orig_quat.conjugated() * psk_bone.parent.axis_vec, axis_vec)
                v = psk_bone.parent.axis_vec.copy()
                v.rotate( psk_bone.orig_quat.conjugated() )
                vec_to_axis_vec(v, axis_vec)

                # reorient bone to other axis bychanging our base Y vec...
                # this is not tested well
                vecy = Vector((1.0, 0.0, 0.0))
            else:
                # @
                # vec_to_axis_vec(psk_bone.orig_quat.conjugated() * psk_bone.parent.axis_vec, axis_vec)
                v = psk_bone.parent.axis_vec.copy()
                v.rotate( psk_bone.orig_quat.conjugated() )
                vec_to_axis_vec(v, axis_vec)

        return (bone_len, vecy.rotation_difference(axis_vec))

    # bone with > 0 children BUT only 1 non orphan bone ( reorient to it! )
    if bDirectly and len(children) > 1:

        childs_with_childs = 0

        for child in filter(lambda c: len(c.children), children):

            childs_with_childs += 1

            if childs_with_childs > 1:
                break

            candidate = child

        if childs_with_childs == 1:
            # print('candidate',psk_bone.name,candidate.name)
            return (len(candidate.orig_loc), vecy.rotation_difference(candidate.orig_loc))

    # bone with > 0 children
    sumvec = Vector()
    sumlen = 0

    for child in children:
        sumvec += (child.orig_loc)
        sumlen += child.orig_loc.length
    sumlen /= len(children)
    sumlen = max(sumlen, 0.01)

    if bDirectly:
        return (sumlen, vecy.rotation_difference(sumvec))

    vec_to_axis_vec(sumvec, axis_vec)
    psk_bone.axis_vec = axis_vec
    return (sumlen, vecy.rotation_difference(axis_vec))


def __pass(*args,**kwargs):
    pass


def util_check_file_header(file, ftype):
    header_bytes = file.read(32)

    if len(header_bytes) < 32:
        return False

    if not header_bytes.startswith( PSKPSA_FILE_HEADER[ftype] ):
        return False

    return True


def color_linear_to_srgb(c):
    """
    Convert from linear to sRGB color space.
    Source: Cycles addon implementation, node_color.h.
    """
    if c < 0.0031308:
        return 0.0 if c < 0.0 else c * 12.92
    else:
        return 1.055 * pow(c, 1.0 / 2.4) - 0.055

def pskimport(filepath,
        context = None,
        bImportmesh = True,
        bImportbone = True,
        bSpltiUVdata = False,
        fBonesize = 5.0,
        fBonesizeRatio = 0.6,
        bDontInvertRoot = True,
        bReorientBones = False,
        bReorientDirectly = False,
        bScaleDown = True,
        bToSRGB = True,
        error_callback = None):
    '''
    Import mesh and skeleton from .psk/.pskx files

    Args:
        bReorientBones:
            Axis based bone orientation to children

        error_callback:
            Called when importing is failed.

            error_callback = lambda msg: print('reason:', msg)

    '''
    if not hasattr( error_callback, '__call__'):
        # error_callback = __pass
        error_callback = print

    # ref_time = time.process_time()
    if not bImportbone and not bImportmesh:
        error_callback("Nothing to do.\nSet something for import.")
        return False

    print ("-----------------------------------------------")
    print ("---------EXECUTING PSK PYTHON IMPORTER---------")
    print ("-----------------------------------------------")

    #file may not exist
    try:
        file = open(filepath,'rb')
    except IOError:
        error_callback('Error while opening file for reading:\n  "'+filepath+'"')
        return False

    if not util_check_file_header(file, 'psk'):
        error_callback('Not psk file:\n  "'+filepath+'"')
        return False

    Vertices = None
    Wedges = None
    Faces = None
    UV_by_face = None
    Materials = None
    Bones = None
    Weights = None
    VertexColors = None
    Extrauvs = []
    Normals = None
    WedgeIdx_by_faceIdx = None

    if not context:
        context = bpy.context
    #==================================================================================================
    # Materials   MaterialNameRaw | TextureIndex | PolyFlags | AuxMaterial | AuxFlags |  LodBias | LodStyle
    # Only Name is usable.
    def read_materials():

        nonlocal Materials

        Materials = []

        for counter in range(chunk_datacount):

            (MaterialNameRaw,) = unpack_from('64s24x', chunk_data, chunk_datasize * counter)

            Materials.append( util_bytes_to_str( MaterialNameRaw ) )


    #==================================================================================================
    # Faces WdgIdx1 | WdgIdx2 | WdgIdx3 | MatIdx | AuxMatIdx | SmthGrp
    def read_faces():

        if not bImportmesh:
            return True

        nonlocal Faces, UV_by_face, WedgeIdx_by_faceIdx

        UV_by_face = [None] * chunk_datacount
        Faces = [None] * chunk_datacount
        WedgeIdx_by_faceIdx = [None] * chunk_datacount

        if len(Wedges) > 65536:
            unpack_format = '=IIIBBI'
        else:
            unpack_format = '=HHHBBI'

        unpack_data = Struct(unpack_format).unpack_from

        for counter in range(chunk_datacount):
            (WdgIdx1, WdgIdx2, WdgIdx3,
             MatIndex,
             AuxMatIndex, #unused
             SmoothingGroup # Umodel is not exporting SmoothingGroups
             ) = unpack_data(chunk_data, counter * chunk_datasize)

            # looks ugly
            # Wedges is (point_index, u, v, MatIdx)
            ((vertid0, u0, v0, matid0), (vertid1, u1, v1, matid1), (vertid2, u2, v2, matid2)) = Wedges[WdgIdx1], Wedges[WdgIdx2], Wedges[WdgIdx3]

            # note order: C,B,A
            # Faces[counter] = (vertid2,  vertid1, vertid0)

            Faces[counter] = (vertid1,  vertid0, vertid2)
            # Faces[counter] = (vertid1,  vertid2, vertid0)
            # Faces[counter] = (vertid0,  vertid1, vertid2)

            # uv = ( ( u2, 1.0 - v2 ), ( u1, 1.0 - v1 ), ( u0, 1.0 - v0 ) )
            uv = ( ( u1, 1.0 - v1 ), ( u0, 1.0 - v0 ), ( u2, 1.0 - v2 ) )

            # Mapping: FaceIndex <=> UV data <=> FaceMatIndex
            UV_by_face[counter] = (uv, MatIndex, (matid2, matid1, matid0))

            # We need this for EXTRA UVs
            WedgeIdx_by_faceIdx[counter] = (WdgIdx3, WdgIdx2, WdgIdx1)


    #==================================================================================================
    # Vertices X | Y | Z
    def read_vertices():

        if not bImportmesh:
            return True

        nonlocal Vertices

        Vertices = [None] * chunk_datacount

        unpack_data = Struct('3f').unpack_from

        if bScaleDown:
            for counter in range( chunk_datacount ):
                (vec_x, vec_y, vec_z) = unpack_data(chunk_data, counter * chunk_datasize)
                Vertices[counter]  = (vec_x*0.01, vec_y*0.01, vec_z*0.01)
                # equal to gltf
                # Vertices[counter]  = (vec_x*0.01, vec_z*0.01, -vec_y*0.01)
        else:
            for counter in range( chunk_datacount ):
                Vertices[counter]  =  unpack_data(chunk_data, counter * chunk_datasize)


    #==================================================================================================
    # Wedges (UV)   VertexId |  U |  V | MatIdx
    def read_wedges():

        if not bImportmesh:
            return True

        nonlocal Wedges

        Wedges = [None] * chunk_datacount

        unpack_data = Struct('=IffBxxx').unpack_from

        for counter in range( chunk_datacount ):
            (vertex_id,
             u, v,
             material_index) = unpack_data( chunk_data, counter * chunk_datasize )

            # print(vertex_id, u, v, material_index)
            # Wedges[counter] = (vertex_id, u, v, material_index)
            Wedges[counter] = [vertex_id, u, v, material_index]

    #==================================================================================================
    # Bones (VBone .. VJointPos ) Name|Flgs|NumChld|PrntIdx|Qw|Qx|Qy|Qz|LocX|LocY|LocZ|Lngth|XSize|YSize|ZSize
    def read_bones():

        nonlocal Bones, bImportbone

        if chunk_datacount == 0:
            bImportbone = False

        if bImportbone:
            # unpack_data = Struct('64s3i11f').unpack_from
            unpack_data = Struct('64s3i7f16x').unpack_from
        else:
            unpack_data = Struct('64s56x').unpack_from

        Bones = [None] * chunk_datacount

        for counter in range( chunk_datacount ):
            Bones[counter] = unpack_data( chunk_data, chunk_datasize * counter)


    #==================================================================================================
    # Influences (Bone Weight) (VRawBoneInfluence) ( Weight | PntIdx | BoneIdx)
    def read_weights():

        nonlocal Weights

        if not bImportmesh:
            return True

        Weights = [None] * chunk_datacount

        unpack_data = Struct('fii').unpack_from

        for counter in range(chunk_datacount):
            Weights[counter] = unpack_data(chunk_data, chunk_datasize * counter)

    #==================================================================================================
    # Vertex colors. R G B A bytes. NOTE: it is Wedge color.(uses Wedges index)
    def read_vertex_colors():

        nonlocal VertexColors

        unpack_data = Struct("=4B").unpack_from

        VertexColors = [None] * chunk_datacount

        for counter in range( chunk_datacount ):
            VertexColors[counter] = unpack_data(chunk_data, chunk_datasize * counter)


    #==================================================================================================
    # Extra UV. U | V
    def read_extrauvs():

        unpack_data = Struct("=2f").unpack_from

        uvdata = [None] * chunk_datacount

        for counter in range( chunk_datacount ):
            uvdata[counter] = unpack_data(chunk_data, chunk_datasize * counter)

        Extrauvs.append(uvdata)

    #==================================================================================================
    # Vertex Normals NX | NY | NZ
    def read_normals():
        if not bImportmesh:
            return True

        nonlocal Normals
        Normals = [None] * chunk_datacount

        unpack_data = Struct('3f').unpack_from

        for counter in range(chunk_datacount):
            Normals[counter] = unpack_data(chunk_data, counter * chunk_datasize)


    CHUNKS_HANDLERS = {
        'PNTS0000': read_vertices,
        'VTXW0000': read_wedges,
        'VTXW3200': read_wedges,#?
        'FACE0000': read_faces,
        'FACE3200': read_faces,
        'MATT0000': read_materials,
        'REFSKELT': read_bones,
        'REFSKEL0': read_bones, #?
        'RAWW0000': read_weights,
        'RAWWEIGH': read_weights,
        'VERTEXCO': read_vertex_colors, # VERTEXCOLOR
        'EXTRAUVS': read_extrauvs,
        'VTXNORMS': read_normals
    }

    #===================================================================================================
    # File. Read all needed data.
    #         VChunkHeader Struct
    # ChunkID|TypeFlag|DataSize|DataCount
    # 0      |1       |2       |3

    while True:

        header_bytes = file.read(32)

        if len(header_bytes) < 32:

            if len(header_bytes) != 0:
                error_callback("Unexpected end of file.(%s/32 bytes)" % len(header_bytes))
            break

        (chunk_id, chunk_type, chunk_datasize, chunk_datacount) = unpack('20s3i', header_bytes)

        chunk_id_str = util_bytes_to_str(chunk_id)
        chunk_id_str = chunk_id_str[:8]

        if chunk_id_str in CHUNKS_HANDLERS:

            chunk_data = file.read( chunk_datasize * chunk_datacount)

            if len(chunk_data) < chunk_datasize * chunk_datacount:
                error_callback('Psk chunk %s is broken.' % chunk_id_str)
                return False

            CHUNKS_HANDLERS[chunk_id_str]()

        else:

            print('Unknown chunk: ', chunk_id_str)
            file.seek(chunk_datasize * chunk_datacount, 1)


        # print(chunk_id_str, chunk_datacount)

    file.close()

    print(" Importing file:", filepath)

    if not bImportmesh and (Bones is None or len(Bones) == 0):
        error_callback("Psk: no skeleton data.")
        return False

    MAX_UVS = 8
    NAME_UV_PREFIX = "UV"

    # file name w/out extension
    gen_name_part = util_gen_name_part(filepath)
    gen_names = {
        'armature_object':  normalize_ue_name(gen_name_part + '.ao', fallback="Armature_Object"),
        'armature_data':    normalize_ue_name(gen_name_part + '.ad', fallback="Armature_Data"),
            'mesh_object':  normalize_ue_name(gen_name_part + '.mo', fallback="Mesh_Object"),
            'mesh_data':    normalize_ue_name(gen_name_part + '.md', fallback="Mesh_Data")
    }

    if bImportmesh:
        mesh_data = bpy.data.meshes.new(normalize_ue_name(gen_names['mesh_data'], fallback="Mesh_Data"))
        mesh_obj = bpy.data.objects.new(normalize_ue_name(gen_names['mesh_object'], fallback="Mesh_Object"), mesh_data)


    #==================================================================================================
    # UV. Prepare
    if bImportmesh:
        if bSpltiUVdata:
        # store how much each "matrial index" have vertices

            uv_mat_ids = {}

            for (_, _, _, material_index) in Wedges:

                if not (material_index in uv_mat_ids):
                    uv_mat_ids[material_index] = 1
                else:
                    uv_mat_ids[material_index] += 1


            # if we have more UV material indexes than blender UV maps, then...
            if bSpltiUVdata and len(uv_mat_ids) > MAX_UVS :

                uv_mat_ids_len = len(uv_mat_ids)

                print('UVs: %s out of %s is combined in a first UV map(%s0)' % (uv_mat_ids_len - 8, uv_mat_ids_len, NAME_UV_PREFIX))

                mat_idx_proxy = [0] * len(uv_mat_ids)

                counts_sorted = sorted(uv_mat_ids.values(), reverse = True)

                new_mat_index = MAX_UVS - 1

                for c in counts_sorted:
                    for mat_idx, counts in uv_mat_ids.items():
                        if c == counts:
                            mat_idx_proxy[mat_idx] = new_mat_index
                            if new_mat_index > 0:
                                new_mat_index -= 1
                            # print('MatIdx remap: %s > %s' % (mat_idx,new_mat_index))

                for i in range(len(Wedges)):
                    Wedges[i][3] = mat_idx_proxy[Wedges[i][3]]

        # print('Wedges:', chunk_datacount)
        # print('uv_mat_ids', uv_mat_ids)
        # print('uv_mat_ids', uv_mat_ids)
        # for w in Wedges:

    if bImportmesh:
        # print("-- Materials -- (index, name, faces)")
        blen_materials = []
        for materialname in Materials:
            materialname = normalize_ue_name(materialname, fallback="PSK_Material")
            matdata = bpy.data.materials.get(materialname)

            if matdata is None:
                matdata = bpy.data.materials.new(normalize_ue_name(materialname, fallback="PSK_Material"))
            # matdata = bpy.data.materials.new( materialname )

            blen_materials.append( matdata )
            mesh_data.materials.append( matdata )
            # print(counter,materialname,TextureIndex)
            # if mat_groups.get(counter) is not None:
                # print("%i: %s" % (counter, materialname), len(mat_groups[counter]))

    #==================================================================================================
    # Prepare bone data
    def init_psk_bone(i, psk_bones, name_raw):
        psk_bone = class_psk_bone()
        psk_bone.children = []
        psk_bone.name = util_bytes_to_str(name_raw)
        psk_bones[i] = psk_bone
        return psk_bone

    psk_bone_name_toolong = False

    # indexed by bone index. array of psk_bone
    psk_bones = [None] * len(Bones)

    if not bImportbone: #data needed for mesh-only import

        for counter,(name_raw,) in enumerate(Bones):
            init_psk_bone(counter, psk_bones, name_raw)

    if bImportbone:  #else?

        # average bone length
        sum_bone_pos = 0

        for counter, (name_raw, flags, NumChildren, ParentIndex, #0 1 2 3
             quat_x, quat_y, quat_z, quat_w,            #4 5 6 7
             vec_x, vec_y, vec_z
            #  ,                       #8 9 10
            #  joint_length,                              #11
            #  scale_x, scale_y, scale_z
             ) in enumerate(Bones):

            psk_bone = init_psk_bone(counter, psk_bones, name_raw)

            psk_bone.bone_index = counter
            psk_bone.parent_index = ParentIndex

            # Tested. 64 is getting cut to 63
            if len(psk_bone.name) > 63:
                psk_bone_name_toolong = True
                # print('Warning. Bone name is too long:', psk_bone.name)

            # make sure we have valid parent_index
            if psk_bone.parent_index < 0:
                psk_bone.parent_index = 0

            # psk_bone.scale = (scale_x, scale_y, scale_z)
            # print("%s: %03f %03f | %f" % (psk_bone.name, scale_x, scale_y, joint_length),scale_x)
            # print("%s:" % (psk_bone.name), vec_x, quat_x)

            # store bind pose to make it available for psa-import via CustomProperty of the Blender bone
            psk_bone.orig_quat = Quaternion((quat_w, quat_x, quat_y, quat_z))

            if bScaleDown:
                psk_bone.orig_loc = Vector((vec_x * 0.01, vec_y * 0.01, vec_z * 0.01))
            else:
                psk_bone.orig_loc = Vector((vec_x, vec_y, vec_z))

            # root bone must have parent_index = 0 and selfindex = 0
            if psk_bone.parent_index == 0 and psk_bone.bone_index == psk_bone.parent_index:
                if bDontInvertRoot:
                    psk_bone.mat_world_rot = psk_bone.orig_quat.to_matrix()
                else:
                    psk_bone.mat_world_rot = psk_bone.orig_quat.conjugated().to_matrix()
                psk_bone.mat_world = Matrix.Translation(psk_bone.orig_loc)

            sum_bone_pos += psk_bone.orig_loc.length


    #==================================================================================================
    # Bones. Calc World-space matrix

        # TODO optimize math.
        for psk_bone in psk_bones:

            if psk_bone.parent_index == 0:
                if psk_bone.bone_index == 0:
                    psk_bone.parent = None
                    continue

            parent = psk_bones[psk_bone.parent_index]

            psk_bone.parent = parent

            parent.children.append(psk_bone)

            # mat_world -     world space bone matrix WITHOUT own rotation
            # mat_world_rot - world space bone rotation WITH own rotation

            # psk_bone.mat_world = parent.mat_world_rot.to_4x4()
            # psk_bone.mat_world.translation = parent.mat_world.translation + parent.mat_world_rot * psk_bone.orig_loc
            # psk_bone.mat_world_rot = parent.mat_world_rot * psk_bone.orig_quat.conjugated().to_matrix()

            psk_bone.mat_world = parent.mat_world_rot.to_4x4()

            v = psk_bone.orig_loc.copy()
            v.rotate( parent.mat_world_rot )
            psk_bone.mat_world.translation = parent.mat_world.translation + v


            psk_bone.mat_world_rot = psk_bone.orig_quat.conjugated().to_matrix()
            psk_bone.mat_world_rot.rotate( parent.mat_world_rot )


            # psk_bone.mat_world =  ( parent.mat_world_rot.to_4x4() * psk_bone.trans)
            # psk_bone.mat_world.translation += parent.mat_world.translation
            # psk_bone.mat_world_rot = parent.mat_world_rot * psk_bone.orig_quat.conjugated().to_matrix()


    #==================================================================================================
    # Skeleton. Prepare.

        armature_data = bpy.data.armatures.new(normalize_ue_name(gen_names['armature_data'], fallback="Armature_Data"))
        armature_obj = bpy.data.objects.new(normalize_ue_name(gen_names['armature_object'], fallback="Armature_Object"),
                                            armature_data)
        # TODO: options for axes and x_ray?
        armature_data.show_axes = False

        armature_data.display_type = 'STICK'
        armature_obj.show_in_front = True

        util_obj_link(context, armature_obj)

        util_select_all(False)
        util_obj_select(context, armature_obj)
        util_obj_set_active(context, armature_obj)

        utils_set_mode('EDIT')


        sum_bone_pos /= len(Bones) # average
        sum_bone_pos *= fBonesizeRatio # corrected

        # bone_size_choosen = max(0.01, round((min(sum_bone_pos, fBonesize))))
        bone_size_choosen = max(0.01, round((min(sum_bone_pos, fBonesize))*100)/100)
        # bone_size_choosen = max(0.01, min(sum_bone_pos, fBonesize))
        # print("Bonesize %f | old: %f round: %f" % (bone_size_choosen, max(0.01, min(sum_bone_pos, fBonesize)),max(0.01, round((min(sum_bone_pos, fBonesize))*100)/100)))

        if not bReorientBones:
            new_bone_size = bone_size_choosen

    #==================================================================================================
    # Skeleton. Build.
        if psk_bone_name_toolong:
            print('Warning. Some bones will be renamed(names are too long). Animation import may be broken.')
            for psk_bone in psk_bones:

                # TODO too long name cutting options?
                orig_long_name = psk_bone.name

                # Blender will cut the name here (>63 chars)
                edit_bone = armature_obj.data.edit_bones.new(psk_bone.name)
                edit_bone["orig_long_name"] = orig_long_name

                # if orig_long_name != edit_bone.name:
                #     print('--')
                #     print(len(orig_long_name),orig_long_name)
                #     print(len(edit_bone.name),edit_bone.name)

                # Use the bone name made by blender (.001 , .002 etc.)
                psk_bone.name = edit_bone.name

        else:
            for psk_bone in psk_bones:
                edit_bone = armature_obj.data.edit_bones.new(psk_bone.name)
                psk_bone.name = edit_bone.name

        for psk_bone in psk_bones:
            edit_bone = armature_obj.data.edit_bones[psk_bone.name]

            armature_obj.data.edit_bones.active = edit_bone

            if psk_bone.parent is not None:
                edit_bone.parent = armature_obj.data.edit_bones[psk_bone.parent.name]
            else:
                if bDontInvertRoot:
                    psk_bone.orig_quat.conjugate()

            if bReorientBones:
                (new_bone_size, quat_orient_diff) = calc_bone_rotation(psk_bone, bone_size_choosen, bReorientDirectly, sum_bone_pos)
                # @
                # post_quat = psk_bone.orig_quat.conjugated() * quat_orient_diff

                post_quat = quat_orient_diff
                post_quat.rotate( psk_bone.orig_quat.conjugated() )
            else:
                post_quat = psk_bone.orig_quat.conjugated()

            # only length of this vector is matter?
            edit_bone.tail = Vector(( 0.0, new_bone_size, 0.0))

            # @
            # edit_bone.matrix = psk_bone.mat_world * post_quat.to_matrix().to_4x4()

            m = post_quat.copy()
            m.rotate( psk_bone.mat_world )

            m = m.to_matrix().to_4x4()
            m.translation = psk_bone.mat_world.translation

            edit_bone.matrix = m


            # some dev code...
            #### FINAL
            # post_quat = psk_bone.orig_quat.conjugated() * quat_diff
            # edit_bone.matrix = psk_bone.mat_world * test_quat.to_matrix().to_4x4()
            # edit_bone["post_quat"] = test_quat
            ####

            # edit_bone["post_quat"] = Quaternion((1,0,0,0))
            # edit_bone.matrix = psk_bone.mat_world* psk_bone.rot


            # if edit_bone.parent:
              # edit_bone.matrix = edit_bone.parent.matrix * psk_bone.trans * (psk_bone.orig_quat.conjugated().to_matrix().to_4x4())
              # edit_bone.matrix = edit_bone.parent.matrix * psk_bone.trans * (test_quat.to_matrix().to_4x4())
            # else:
              # edit_bone.matrix = psk_bone.orig_quat.to_matrix().to_4x4()


            # save bindPose information for .psa import
            # dev
            edit_bone["orig_quat"] = psk_bone.orig_quat
            edit_bone["orig_loc"]  = psk_bone.orig_loc
            edit_bone["post_quat"] = post_quat

            '''
            bone = edit_bone
            if psk_bone.parent is not None:
                orig_loc  =  bone.matrix.translation - bone.parent.matrix.translation
                orig_loc.rotate( bone.parent.matrix.to_quaternion().conjugated() )


                orig_quat = bone.matrix.to_quaternion()
                orig_quat.rotate( bone.parent.matrix.to_quaternion().conjugated()  )
                orig_quat.conjugate()

                if orig_quat.dot( psk_bone.orig_quat ) < 0.95:
                    print(bone.name, psk_bone.orig_quat, orig_quat, orig_quat.dot( psk_bone.orig_quat ))
                    print('parent:', bone.parent.matrix.to_quaternion(), bone.parent.matrix.to_quaternion().rotation_difference(bone.matrix.to_quaternion()) )


                if (psk_bone.orig_loc - orig_loc).length > 0.02:
                    print(bone.name, psk_bone.orig_loc, orig_loc, (psk_bone.orig_loc - orig_loc).length)
            '''
    utils_set_mode('OBJECT')

    #==================================================================================================
    # Weights
    if bImportmesh:

        vertices_total = len(Vertices)

        for ( _, PointIndex, BoneIndex ) in Weights:
            if PointIndex < vertices_total: # can it be not?
                psk_bones[BoneIndex].have_weight_data = True
            # else:
                # print(psk_bones[BoneIndex].name, 'for other mesh',PointIndex ,vertices_total)

            #print("weight:", PointIndex, BoneIndex, Weight)
        # Weights.append(None)
        # print(Weights.count(None))


    # Original vertex colorization code
    '''
    # Weights.sort( key = lambda wgh: wgh[0])
    if bImportmesh:
        VtxCol = []
        bones_count = len(psk_bones)
        for x in range(bones_count):
            #change the overall darkness of each material in a range between 0.1 and 0.9
            tmpVal = ((float(x) + 1.0) / bones_count * 0.7) + 0.1
            tmpVal = int(tmpVal * 256)
            tmpCol = [tmpVal, tmpVal, tmpVal, 0]
            #Change the color of each material slightly
            if x % 3 == 0:
                if tmpCol[0] < 128:
                    tmpCol[0] += 60
                else:
                    tmpCol[0] -= 60
            if x % 3 == 1:
                if tmpCol[1] < 128:
                    tmpCol[1] += 60
                else:
                    tmpCol[1] -= 60
            if x % 3 == 2:
                if tmpCol[2] < 128:
                    tmpCol[2] += 60
                else:
                    tmpCol[2] -= 60
            #Add the material to the mesh
            VtxCol.append(tmpCol)

    for x in range(len(Tmsh.faces)):
        for y in range(len(Tmsh.faces[x].v)):
            #find v in Weights[n][0]
            findVal = Tmsh.faces[x].v[y].index
            n = 0
            while findVal != Weights[n][0]:
                n = n + 1
            TmpCol = VtxCol[Weights[n][1]]
            #check if a vertex has more than one influence
            if n != len(Weights) - 1:
                if Weights[n][0] == Weights[n + 1][0]:
                    #if there is more than one influence, use the one with the greater influence
                    #for simplicity only 2 influences are checked, 2nd and 3rd influences are usually very small
                    if Weights[n][2] < Weights[n + 1][2]:
                        TmpCol = VtxCol[Weights[n + 1][1]]
        Tmsh.faces[x].col.append(NMesh.Col(TmpCol[0], TmpCol[1], TmpCol[2], 0))
    '''

    #===================================================================================================
    # UV. Setup.

    if bImportmesh:
        # Trick! Create UV maps BEFORE mesh and get (0,0) coordinates for free!
        #   ...otherwise UV coords will be copied from active, or calculated from mesh...

        if bSpltiUVdata:

            for i in range(len(uv_mat_ids)):
                get_uv_layers(mesh_data).new(name = NAME_UV_PREFIX + str(i))

        else:

            get_uv_layers(mesh_data).new(name = NAME_UV_PREFIX+"_SINGLE")


        for counter, uv_data in enumerate(Extrauvs):

            if len(mesh_data.uv_layers) < MAX_UVS:

                get_uv_layers(mesh_data).new(name = "EXTRAUVS"+str(counter))

            else:

                Extrauvs.remove(uv_data)
                print('Extra UV layer %s is ignored. Re-import without "Split UV data".' % counter)

    #==================================================================================================
    # Mesh. Build.

        mesh_data.from_pydata(Vertices,[],Faces)

    #==================================================================================================
    # Vertex Normal. Set.

        configure_mesh_normals(mesh_data, Normals)

    #===================================================================================================
    # UV. Set.

    if bImportmesh:

        for face in mesh_data.polygons:
            face.material_index = UV_by_face[face.index][1]

        uv_layers = mesh_data.uv_layers

        if not bSpltiUVdata:
           uvLayer = uv_layers[0]

        # per face
        # for faceIdx, (faceUVs, faceMatIdx, _, _, wmidx) in enumerate(UV_by_face):
        for faceIdx, (faceUVs, faceMatIdx, WedgeMatIds) in enumerate(UV_by_face):

            # per vertex
            for vertN, uv in enumerate(faceUVs):
                loopId = faceIdx * 3 + vertN

                if bSpltiUVdata:
                    uvLayer = uv_layers[WedgeMatIds[vertN]]

                uvLayer.data[loopId].uv = uv

    #==================================================================================================
    # VertexColors

        if VertexColors is not None:

            vtx_color_layer = mesh_data.vertex_colors.new(name = "PSKVTXCOL_0", do_init = False)

            pervertex = [None] * len(Vertices)

            for counter, (vertexid,_,_,_) in enumerate(Wedges):

                # Is it possible ?
                if (pervertex[vertexid] is not None) and (pervertex[vertexid] != VertexColors[counter]):
                    print('Not equal vertex colors. ', vertexid, pervertex[vertexid], VertexColors[counter])

                pervertex[vertexid] = VertexColors[counter]


            for counter, loop in enumerate(mesh_data.loops):

                color = pervertex[ loop.vertex_index ]

                if color is None:
                    vtx_color_layer.data[ counter ].color = (1.,1.,1.,1.)
                else:
                    if bToSRGB:
                        vtx_color_layer.data[ counter ].color = (
                            color_linear_to_srgb(color[0] / 255),
                            color_linear_to_srgb(color[1] / 255),
                            color_linear_to_srgb(color[2] / 255),
                            color[3] / 255
                        )
                    else:
                        vtx_color_layer.data[ counter ].color = (
                            color[0] / 255,
                            color[1] / 255,
                            color[2] / 255,
                            color[3] / 255
                        )

    #===================================================================================================
    # Extra UVs. Set.

        # for counter, uv_data in enumerate(Extrauvs):

        #     uvLayer = mesh_data.uv_layers[ counter - len(Extrauvs) ]

        #     for uv_index, uv_coords in enumerate(uv_data):

        #         uvLayer.data[uv_index].uv = (uv_coords[0], 1.0 - uv_coords[1])


        for counter, uv_data in enumerate(Extrauvs):

            uvLayer = mesh_data.uv_layers[ counter - len(Extrauvs) ]

            for faceIdx, (WedgeIdx3,WedgeIdx2,WedgeIdx1) in enumerate(WedgeIdx_by_faceIdx):

                # equal to gltf
                uvLayer.data[faceIdx*3  ].uv = (uv_data[WedgeIdx2][0], 1.0 - uv_data[WedgeIdx2][1])
                uvLayer.data[faceIdx*3+1].uv = (uv_data[WedgeIdx1][0], 1.0 - uv_data[WedgeIdx1][1])
                uvLayer.data[faceIdx*3+2].uv = (uv_data[WedgeIdx3][0], 1.0 - uv_data[WedgeIdx3][1])
                # uvLayer.data[faceIdx*3  ].uv = (uv_data[WedgeIdx3][0], 1.0 - uv_data[WedgeIdx3][1])
                # uvLayer.data[faceIdx*3+1].uv = (uv_data[WedgeIdx2][0], 1.0 - uv_data[WedgeIdx2][1])
                # uvLayer.data[faceIdx*3+2].uv = (uv_data[WedgeIdx1][0], 1.0 - uv_data[WedgeIdx1][1])


    #===================================================================================================
    # Mesh. Vertex Groups. Bone Weights.

        for psk_bone in psk_bones:
            if psk_bone.have_weight_data:
                psk_bone.vertex_group = mesh_obj.vertex_groups.new(name = psk_bone.name)
            # else:
                # print(psk_bone.name, 'have no influence on this mesh')

        for weight, vertex_id, bone_index_w in filter(None, Weights):
            psk_bones[bone_index_w].vertex_group.add((vertex_id,), weight, 'ADD')


    #===================================================================================================
    # Skeleton. Colorize.

    if bImportbone:

        # Pose bone groups were removed from Blender 4.0. They were only used
        # for viewport coloring, so skip this cosmetic block on current Blender
        # versions while retaining it for older compatible runtimes.
        pose_bone_groups = getattr(armature_obj.pose, "bone_groups", None)
        if pose_bone_groups is not None:
            bone_group_unused = pose_bone_groups.new(name = "Unused bones")
            bone_group_unused.color_set = 'THEME14'

            bone_group_nochild = pose_bone_groups.new(name = "No children")
            bone_group_nochild.color_set = 'THEME03'

            if hasattr(armature_data, "show_group_colors"):
                armature_data.show_group_colors = True

            for psk_bone in psk_bones:

                pose_bone = armature_obj.pose.bones[psk_bone.name]

                if psk_bone.have_weight_data:

                    if len(psk_bone.children) == 0:
                        pose_bone.bone_group = bone_group_nochild

                else:
                    pose_bone.bone_group = bone_group_unused


    #===================================================================================================
    # Final

    if bImportmesh:

        util_obj_link(context, mesh_obj)
        util_select_all(False)


        if not bImportbone:

            util_obj_select(context, mesh_obj)
            util_obj_set_active(context, mesh_obj)

        else:
            # select_all(False)
            util_obj_select(context, armature_obj)

            # parenting mesh to armature object
            mesh_obj.parent = armature_obj
            mesh_obj.parent_type = 'OBJECT'

            # add armature modifier
            blender_modifier = mesh_obj.modifiers.new( armature_obj.data.name, type = 'ARMATURE')
            blender_modifier.show_expanded = False
            blender_modifier.use_vertex_groups = True
            blender_modifier.use_bone_envelopes = False
            blender_modifier.object = armature_obj

            # utils_set_mode('OBJECT')
            # select_all(False)
            util_obj_select(context, armature_obj)
            util_obj_set_active(context, armature_obj)

    # print("Done: %f sec." % (time.process_time() - ref_time))
    utils_set_mode('OBJECT')
    return True


__all__ = ("pskimport",)
