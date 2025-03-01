"""
Structural analysis on a Pegasus wing model
-----------------------------------------------------------
Note: to run the example with the mesh files associated, you need to
have `git lfs` installed to download the actual mesh files. Please
refer to instructions on their official website at https://git-lfs.github.com/
-----------------------------------------------------------
"""
from dolfinx.io import XDMFFile
from dolfinx.fem.petsc import (assemble_vector, assemble_matrix, apply_lifting)
from dolfinx.fem import assemble_scalar
from dolfinx.fem import (locate_dofs_topological, locate_dofs_geometrical,
                        dirichletbc, form, Constant, VectorFunctionSpace)
from dolfinx.mesh import locate_entities
import numpy as np
from mpi4py import MPI
from shell_analysis_fenicsx import *
from shell_analysis_fenicsx.read_properties import readCLT, sortIndex


file_name = "pegasus_6257_quad_SI.xdmf"
path = "../../mesh/mesh-examples/pegasus/mesh_from_michael_SI/"
mesh_file = path + file_name
with XDMFFile(MPI.COMM_WORLD, mesh_file, "r") as xdmf:
       shell_mesh = xdmf.read_mesh(name="Grid")
# sometimes it should be `name="mesh"` to avoid the error
nel = shell_mesh.topology.index_map(shell_mesh.topology.dim).size_local
nn = shell_mesh.topology.index_map(0).size_local

E_val = 6.8E10 # unit: Pa (N/m^2)
nu_val = 0.35
h_val = 3E-3 # overall thickness (unit: m)

# Scaled body force
f_d = 10. # force per unit area (unit: N/m^2)

E = Constant(shell_mesh,E_val) # Young's modulus
nu = Constant(shell_mesh,nu_val) # Poisson ratio

# ################## Constant thickness  ###################
# h = Constant(shell_mesh,h_val) # Shell thickness

################### Varying thickness distribution ###################
hrcs = np.reshape(np.loadtxt(path+'pegasus_t_med_SI.csv'),(nn,1))
h_nodal = np.arange(nn)
node_indices = shell_mesh.geometry.input_global_indices
h_array = sortIndex(hrcs, h_nodal, node_indices)
## Apply element-wise thickness ###
VT = FunctionSpace(shell_mesh, ("CG", 1))
h_cg1 = Function(VT)
h_cg1.vector.setArray(h_array)

V0 = FunctionSpace(shell_mesh, ('DG', 0))
h = Function(V0)
project(h_cg1, h, lump_mass=False)
# f = as_vector([0,0,f_d]) # Body force per unit area


element_type = "CG2CG1"
#element_type = "CG2CR1"


element = ShellElement(
                shell_mesh,
                element_type,
#                inplane_deg=3,
#                shear_deg=3
                )

# VE1 = VectorElement("Lagrange",shell_mesh.ufl_cell(),1)
# WE = MixedElement([VE1,VE1])
# W = FunctionSpace(shell_mesh,WE)

W = element.W
w = Function(W)
dx_inplane, dx_shear = element.dx_inplane, element.dx_shear

################# Apply concentrated forces #################

x0 = np.load("coords_SI.npy")
f_c = np.load("loads_SI.npy")

from FSI_coupling.VLM_sim_handling import *
from FSI_coupling.shellmodule_utils import *
from FSI_coupling.NodalMapping import *
from FSI_coupling.NodalMapping import *
from FSI_coupling.mesh_handling_utils import *
from FSI_coupling.array_handling_utils import *
from FSI_coupling.shellmodule_csdl_interface import (
                                DisplacementMappingImplicitModel,
                                ForceMappingModel,
                                VLMForceIOModel,
                                VLMMeshUpdateModel
                                )


# Define force functions and aero-elastic coupling object ########
coupling_obj = FEniCSx_concentrated_load_coupling(shell_mesh, x0,
                    W, RBF_width_par=2.)
# print("G mat shape:", np.shape(coupling_obj.G_mat.map))
f_array = coupling_obj.compute_dist_solid_force_from_point_load(f_c)

# print(f_array.shape)
# apply array in function space
VF = VectorFunctionSpace(shell_mesh, ("CG", 1))
f = Function(VF)
f.vector.setArray(0.001*f_array) # Body force per unit area

# ###############################################################


#### Compute the CLT model from the material properties (for single-layer material)
material_model = MaterialModel(E=E,nu=nu,h=h)
elastic_model = ElasticModel(shell_mesh,w,material_model.CLT)
elastic_energy = elastic_model.elasticEnergy(E, h, dx_inplane,dx_shear)
F = elastic_model.weakFormResidual(elastic_energy, f)

############ Set the BCs for the airplane model ###################

u0 = Function(W)
u0.vector.set(0.0)


locate_BC1 = locate_dofs_geometrical((W.sub(0), W.sub(0).collapse()[0]),
                                    lambda x: np.less(x[1], 1e-6))
locate_BC2 = locate_dofs_geometrical((W.sub(1), W.sub(1).collapse()[0]),
                                    lambda x: np.less(x[1], 1e-6))
ubc=  Function(W)
with ubc.vector.localForm() as uloc:
     uloc.set(0.)

bcs = [dirichletbc(ubc, locate_BC1, W.sub(0)),
        dirichletbc(ubc, locate_BC2, W.sub(1)),
       ]

########### Apply the point load #############################

f1 = Function(W)
f1_0,_ = f1.split()
f1_0.interpolate(f)

# Assemble linear system
a = derivative(F,w)
L = -F
A = assemble_matrix(form(a), bcs)
A.assemble()
b = assemble_vector(form(L))
b.setArray(f1.vector.getArray())
b.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
dolfinx.fem.set_bc(b, bcs)



######### Solve the linear system with KSP solver ############
solveKSP_mumps(A, b, w.vector)

# ########## Solve with Newton solver wrapper: ##########
# from timeit import default_timer
# start = default_timer()
# solveNonlinear(F,w,bcs,log=True)
# stop = default_timer()
# print("Time for solve nonlinear:", stop-start)
# ########## Output: ##############

u_mid, _ = w.split()

dofs = len(w.vector.getArray())

uZ = computeNodalDisp(w.sub(0))[2]
strain_energy = assemble_scalar(form(elastic_energy))


shell_stress_RM = ShellStressRM(shell_mesh, w, h, E, nu)
von_Mises_top = shell_stress_RM.vonMisesStress(h/2)
V1 = FunctionSpace(shell_mesh, ('CG', 1))
von_Mises_top_func = Function(V1)
project(von_Mises_top, von_Mises_top_func, lump_mass=False)

metadata = {"quadrature_degree": 4}
dxx = ufl.Measure("dx", domain=shell_mesh, metadata=metadata)

def max_vm_stress_cg1(vm_stress,dx,rho=200,alpha=None,m=1e-6):
    """
    Compute the maximum von Mises stress via p-norm
    `rho` is the Constraint aggregation factor
    """
    pnorm = (m*vm_stress)**rho*dx

    if alpha == None:
        # alpha is an estimation of the surface area
        # alpha_form = Constant(shell_mesh,1.0)*dx
        h_mesh = ufl.CellDiameter(shell_mesh)
        alpha_form = h_mesh**2/2*dx
        alpha = assemble_scalar(form(alpha_form))
    pnorm_val = 1/alpha*assemble_scalar(form(pnorm))
    max_vm_stress = 1/m*(pnorm_val)**(1/rho)
    # max_vm_stress = 1/alpha*pnorm_val
    return max_vm_stress

def max_vm_stress_exp(vm_stress,dx,rho=200,alpha=None,m=1e-6):
    """
    Compute the maximum von Mises stress via p-norm
    `rho` is the Constraint aggregation factor
    """
    pnorm = (m*vm_stress)**rho*dx

    if alpha == None:
        # alpha is a parameter based on the surface area
        alpha_form = Constant(shell_mesh,1.0)*dx
        alpha = assemble_scalar(form(alpha_form))

    pnorm_val = 1/alpha*assemble_scalar(form(pnorm))
    max_vm_stress_form = 1/m*(pnorm_val)**(1/rho)
    # max_vm_stress = 1/alpha*pnorm_val
    return max_vm_stress_form

def dmax_vmdw(w,vm_stress,dx,rho=200,alpha=None,m=1e-6):
    max_vm_form = max_vm_stress_exp(vm_stress,dx,rho=200,alpha=None,m=1e-6)
    return derivative(max_vm_form, w)


# alpha is a parameter based on the cell area
h_mesh = ufl.CellDiameter(shell_mesh)
V1 = FunctionSpace(shell_mesh, ('CG', 1))
h_mesh_func = Function(V1)
project(h_mesh, h_mesh_func, lump_mass=False)
alpha = np.average(h_mesh_func.vector.getArray())**2/2

print("-"*50)
print("-"*8, file_name, "-"*9)
print("-"*50)
print("Tip deflection:", max(uZ))
# print("Tip deflection:", uZ_tip)
print("Total strain energy:", strain_energy)
print("Exact maximum von Mises stress:", np.max(von_Mises_top_func.vector.getArray()))
# print("Derivative of maximum von Mises stress wrt displacements:", np.linalg.norm(assemble_vector(dmax_vmdw).getArray()))
rho_list = [50, 100, 200]
# rho_list = [200]
print("rho     ", "Maximum von von Mises stress")
for rho in rho_list:
    print(rho, max_vm_stress_exp(von_Mises_top,dx=dxx,rho=rho,m=1e-6, alpha=alpha))
print("  Number of elements = "+str(shell_mesh.topology.index_map(shell_mesh.topology.dim).size_local))
print("  Number of vertices = "+str(shell_mesh.topology.index_map(0).size_local))
print("  Number of total dofs = ", dofs)
print("-"*50)

with XDMFFile(MPI.COMM_WORLD, "solutions_varied_thickness/u_mid_tri.xdmf", "w") as xdmf:
    xdmf.write_mesh(shell_mesh)
    xdmf.write_function(u_mid)
with XDMFFile(MPI.COMM_WORLD, "solutions_varied_thickness/thickness_nodal.xdmf", "w") as xdmf:
    xdmf.write_mesh(shell_mesh)
    xdmf.write_function(h)
with XDMFFile(MPI.COMM_WORLD, "solutions_varied_thickness/thickness_cell.xdmf", "w") as xdmf:
    xdmf.write_mesh(shell_mesh)
    xdmf.write_function(h)
with XDMFFile(MPI.COMM_WORLD, "solutions_varied_thickness/von_Mises_top.xdmf", "w") as xdmf:
    xdmf.write_mesh(shell_mesh)
    xdmf.write_function(von_Mises_top_func)
with XDMFFile(MPI.COMM_WORLD, "solutions_varied_thickness/distributed_force.xdmf", "w") as xdmf:
    xdmf.write_mesh(shell_mesh)
    xdmf.write_function(f)

######## CG1 for thickness ############
#Tip deflection: 0.00390570198922115
# Total strain energy: 0.20645649199006852
# Exact maximum von Mises stress: 1277419.7573925648
# rho      Maximum von von Mises stress Maximum von von Mises stress with projection
######## alpha is the surface area ################
# 50 1122760.9064817019 1085074.2262531158
# 100 1189102.6262474859 1160819.214049161
# 200 1224696.408708455 1209273.6568247357
# *400 1242977.2722999894 1238570.7851096962
# 600 1249132.0564165474 1249695.2977195713
##################################################
######## alpha is the average cell area ################
# 50 1209710.2121978658
# 100 1234287.6128997768
# 200 1247748.2241445126
# **400 1254620.691484869
# 600 1256920.6436763916
##################################################
######## alpha is the minimum cell area ################
# 50 1309340.751644708
# 100 1284109.4426109013
# 200 1272681.6869550287
# 400 1267094.0833519457
# 600 1265237.738776852
##################################################

######## DG0 for thickness - stress only ############
# Tip deflection: 0.00390570198922115
# Total strain energy: 0.20645649199006852
# Exact maximum von Mises stress: 1291642.4525800098
# rho      Maximum von von Mises stress Maximum von von Mises stress with projection
######## alpha is the surface area ################
# 50 1244028.9991175844 1147122.2063260726
# 100 1259250.611054704 1193741.3867913324
# 200 1272959.7076320443 1227353.352623823
# 400 1279973.118284999 1252829.5319798794
# 600 1282319.5468170522 1263824.5950317665
##################################################


######## DG0 for thickness - whole model ############
# Tip deflection: 0.003909941204054876
# Total strain energy: 0.20665997024742508
# Exact maximum von Mises stress: 1299698.644367395
# rho      Maximum von von Mises stress Maximum von von Mises stress with projection
######## alpha is the surface area ################
# 50 1246585.278520244 1148303.0553861375
# 100 1262774.2670024284 1195821.3187346677
# 200 1276550.7859816216 1232351.0694762857
# 400 1283583.99577308 1260390.4117856463
# 600 1285937.043714231 1271626.8675979346
##################################################
# x0_ = np.array([[[9.864598,	0.9858248,	1.0422636]],
#                 [[9.882632,	2.042033,	1.0631932]],
#                 [[9.89457,	2.742946,	1.0774172]],
#                 [[9.906762,	3.443986,	1.0918952]],
#                 [[9.918954,	4.14528,	1.1066272]],
#                 [[9.9314,	4.84632,	1.121664]],
#                 [[9.943338,	5.54736,	1.1333734]],
#                 [[9.952736,	6.248908,	1.1309604]],
#                 [[9.962388,	6.950202,	1.1286744]],
#                 [[9.972294,	7.65175,	1.1263884]],
#                 [[9.981946,	8.353044,	1.1241024]],
#                 [[9.991852,	9.054592,	1.1218164]],
#                 [[10.001504,	9.755886,	1.1195304]],
#                 [[10.01141,	10.457434,	1.1172444]],
#                 [[10.021316,	11.158728,	1.114933]],
#                 [[10.031222,	11.860276,	1.1126216]],
#                 [[10.036302,	12.215622,	1.1114532]],])
# f_c_ = np.array([57.17741988,	0,	7147.844718,
#                 36.05994025,	0,	7527.277884,
#                 4.922845074,	0,	7796.395194,
#                 -28.30313422,	0,	7040.197794,
#                 -56.13208818,	0,	6313.358646,
#                 -77.31896004,	0,	5619.436326,
#                 -95.37428502,	0,	5104.33245,
#                 -93.52827372,	0,	4550.084238,
#                 -81.41132244,	0,	4004.243162,
#                 -73.07535816,	0,	3642.424947,
#                 -65.388834,	0,	3304.760567,
#                 -58.31171598,	0,	2986.490426,
#                 -50.9543601,	0,	2667.419605,
#                 -43.56275293,	0,	2334.692749,
#                 -34.59469658,	0,	1962.910522,
#                 -21.27405697,	0,	1338.11354,
#                 -8.494765734,	0,	630.7131138,
#                 ])
# np.save("coords_SI.npy", x0_)
# np.save("loads_SI.npy", f_c_)

"""
Observations from numerical experiments:
>> CG1 space for thickness would lead to strange stress concentration at
    the wing tip ---> using DG0 for thickness can solve this problem
>> Better accuracy when using cell area as `alpha`
>> Sufficient accuracy (2%) & low computational cost when choosing rho = 200
"""
