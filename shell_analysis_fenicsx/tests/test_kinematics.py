import kinematics

import numpy as np
import lsdo_test as lt

from ufl import (sqrt, as_vector)

#### ------------------------- ####
#       Test kinematics.unit      #
#### ------------------------- ####

##test struct struct_kinematics
def test_unit_1():
    """
    This test checks whether `kinematics.unit` produces correct outputs
    """
    # test input
    test_vec = as_vector((1, 1, 1))
    # hand-computed reference output
    ref_output = as_vector((1/np.sqrt(3), 1/np.sqrt(3), 1/np.sqrt(3)))
    # output computed with kinematics.unit()
    unit_output = unit(test_vec)
    # compute max component error (L_infinity error) between reference and computed output 
    compare_error = norm(unit_output - ref_output, 'linf')

    assert lt.equal(compare_error, 0., tol=1e-10)

##test struct struct_kinematics
def test_unit_2():
    """
    This test checks whether `kinematics.unit` produces correct outputs
    """
    # test input
    test_vec = as_vector((1, -3, 0))
    # hand-computed reference output    
    ref_output = as_vector((1/np.sqrt(10), -3/np.sqrt(10), 0))
    # output computed with kinematics.unit()
    unit_output = unit(test_vec)
    # compute max component error (L_infinity error) between reference and computed output 
    compare_error = norm(unit_output - ref_output, 'linf')

    assert lt.equal(compare_error, 0., tol=1e-10)