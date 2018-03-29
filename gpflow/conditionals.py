# Copyright 2016 Valentine Svensson, James Hensman, alexggmatthews
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import tensorflow as tf

from . import settings, mean_functions
from .decors import name_scope
from .dispatch import conditional, sample_conditional
from .expectations import expectation
from .features import Kuu, Kuf, InducingPoints, InducingFeature
from .kernels import Kernel, Combination
from .probability_distributions import Gaussian

float_type = settings.float_type
jitter_level = settings.numerics.jitter_level


def expand_independent_outputs(fvar, full_cov, full_cov_output):
    """
    Reshapes fvar to the correct shape, specified by `full_cov` and `full_cov_output`.

    :param fvar: has shape N x P (full_cov = False) or P x N x N (full_cov = True).
    :return:
        1) full_cov: True and full_cov_output: True
            fvar N x P x N x P
        2) full_cov: True and full_cov_output: False
            fvar P x N x N
        3) full_cov: False and full_cov_output: True
            fvar N x P x P
        4) full_cov: False and full_cov_output: False
            fvar N x P
    """
    if full_cov and full_cov_output:
        fvar = tf.matrix_diag(tf.transpose(fvar))   # N x N x P x P
        fvar = tf.transpose(fvar, [0, 2, 1, 3])  # N x P x N x P
    if not full_cov and full_cov_output:
        fvar = tf.matrix_diag(fvar)   # N x P x P
    if full_cov and not full_cov_output:
        pass  # P x N x N
    if not full_cov and not full_cov_output:
        pass  # N x P
    
    return fvar


# ----------------------------------------------------------------------------
############################### CONDITIONAL ##################################
# ----------------------------------------------------------------------------

@conditional.register(object, InducingFeature, Kernel, object)
@name_scope("conditional")
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    Single-output GP allowing repetitions.
    See ``_conditional`` below for further reference
    :param Xnew: N x D
    :param f: M x R
    :param q_sqrt: M x R  or  R x M x M
    :return: 
        - mean:     N x R
        - variance: N x R, R x N x N  or  N x R x R  or  N x R x N x R
    """
    print("Conditional: Inducing Feature - Kernel")
    print(full_cov, full_cov_output)
    Kmm = Kuu(feat, kern, jitter=settings.numerics.jitter_level)  # M x M
    Kmn = Kuf(feat, kern, Xnew)  # M x N
    Knn = kern.K(Xnew) if full_cov else kern.Kdiag(Xnew)

    fmean, fvar = base_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, 
                                   q_sqrt=q_sqrt, white=white)  # N x R,  R x N x N or N x R
    return fmean, expand_independent_outputs(fvar, full_cov, full_cov_output)


@conditional.register(object, object, Kernel, object)
@name_scope("conditional")
def _conditional(Xnew, X, kern, f, *, full_cov=False, q_sqrt=None, white=False):
    """
    Given f, representing the GP at the points X, produce the mean and
    (co-)variance of the GP at the points Xnew.

    Additionally, there may be Gaussian uncertainty about f as represented by
    q_sqrt. In this case `f` represents the mean of the distribution and
    q_sqrt the square-root of the covariance.

    Additionally, the GP may have been centered (whitened) so that
        p(v) = N(0, I)
        f = L v
    thus
        p(f) = N(0, LL^T) = N(0, K).
    In this case `f` represents the values taken by v.

    The method can either return the diagonals of the covariance matrix for
    each output (default) or the full covariance matrix (full_cov=True).

    We assume R independent GPs, represented by the columns of f (and the
    last dimension of q_sqrt).

    :param Xnew: data matrix, size N x D.
    :param X: data points, size M x D.
    :param kern: GPflow kernel.
    :param f: data matrix, M x R, representing the function values at X,
        for K functions.
    :param q_sqrt: matrix of standard-deviations or Cholesky matrices,
        size M x R or R x M x M.
    :param white: boolean of whether to use the whitened representation as
        described above.
    :return: 
        - mean:     N x P
        - variance: N x P (full_cov = False), P x N x N (full_cov = True)
    """
    print("Conditional: Kernel")
    print(full_cov)
    num_data = tf.shape(X)[0]  # M
    Kmm = kern.K(X) + tf.eye(num_data, dtype=settings.float_type) * settings.numerics.jitter_level
    Kmn = kern.K(X, Xnew)
    if full_cov:
        Knn = kern.K(Xnew)
    else:
        Knn = kern.Kdiag(Xnew)
    mean, var = base_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, q_sqrt=q_sqrt, white=white)

    return mean, var  # N x P, N x P or P x N x N


# ----------------------------------------------------------------------------
############################ SAMPLE CONDITIONAL ##############################
# ----------------------------------------------------------------------------

def sample_mvn(mean, cov, cov_structure):
    eps = tf.random_normal(tf.shape(mean), dtype=float_type)  # N x P
    if cov_structure == "diag":
        sample = mean + tf.sqrt(cov) * eps  # N x P
    elif cov_structure == "full":
        cov = cov + (tf.eye(tf.shape(mean)[1], dtype=float_type) * jitter_level)[None, ...]  # N x P x P
        chol = tf.cholesky(cov)  # N x P x P
        return mean + (tf.matmul(chol, eps[..., None])[..., 0])  # N x P
    else:
        raise NotImplementedError
    
    return sample  # N x P


@sample_conditional.register(object, InducingFeature, Kernel, object)
@name_scope("sample_conditional")
def _sample_conditional(Xnew, feat, kern, f, *, full_cov_output=False, q_sqrt=None, white=False):
    """
    Returns a single sample from the conditional posterior.
    :return:
        sample N x P
    """
    print("sample conditional: InducingFeature Kernel")
    mean, var = conditional(Xnew, feat, kern, f, full_cov=False, full_cov_output=full_cov_output,
                            q_sqrt=q_sqrt, white=white)  # N x P, N x P (x P)
    cov_structure = "full" if full_cov_output else "diag"
    return sample_mvn(mean, var, cov_structure)


@sample_conditional.register(object, object, Kernel, object)
@name_scope("sample_conditional")
def _sample_conditional(Xnew, X, kern, f, *, q_sqrt=None, white=False):
    print("sample conditional: Kernel")
    mean, var = conditional(Xnew, X, kern, f, q_sqrt=q_sqrt, white=white, full_cov=False)  # N x P, N x P
    return sample_mvn(mean, var, "diag")  # N x P


# ----------------------------------------------------------------------------
############################# CONDITIONAL MATHS ##############################
# ----------------------------------------------------------------------------

@name_scope()
def base_conditional(Kmn, Kmm, Knn, f, *, full_cov=False, q_sqrt=None, white=False):
    """
    Given a g1 and g2, and distribution p and q such that
      p(g2) = N(g2;0,Kmm)
      p(g1) = N(g1;0,Knn)
      p(g1|g2) = N(g1;0,Knm)
    And
      q(g2) = N(g2;f,q_sqrt*q_sqrt^T)
    This method computes the mean and (co)variance of
      q(g1) = \int q(g2) p(g1|g2)
    :param Kmn: M x N
    :param Kmm: M x M
    :param Knn: N x N  or  N
    :param f: M x R
    :param full_cov: bool
    :param q_sqrt: None or R x M x M (lower triangular)
    :param white: bool
    :return: N x R  or R x N x N
    """
    print("base conditional")
    # compute kernel stuff
    num_func = tf.shape(f)[1]  # R
    Lm = tf.cholesky(Kmm)

    # Compute the projection matrix A
    A = tf.matrix_triangular_solve(Lm, Kmn, lower=True)

    # compute the covariance due to the conditioning
    if full_cov:
        fvar = Knn - tf.matmul(A, A, transpose_a=True)
        fvar = tf.tile(fvar[None, :, :], [num_func, 1, 1])  # R x N x N
    else:
        fvar = Knn - tf.reduce_sum(tf.square(A), 0)
        fvar = tf.tile(fvar[None, :], [num_func, 1])  # R x N

    # another backsubstitution in the unwhitened case
    if not white:
        A = tf.matrix_triangular_solve(tf.transpose(Lm), A, lower=False)

    # construct the conditional mean
    fmean = tf.matmul(A, f, transpose_a=True)

    if q_sqrt is not None:
        if q_sqrt.get_shape().ndims == 2:
            LTA = A * tf.expand_dims(tf.transpose(q_sqrt), 2)  # R x M x N
        elif q_sqrt.get_shape().ndims == 3:
            L = tf.matrix_band_part(q_sqrt, -1, 0)  # R x M x M
            A_tiled = tf.tile(tf.expand_dims(A, 0), tf.stack([num_func, 1, 1]))
            LTA = tf.matmul(L, A_tiled, transpose_a=True)  # R x M x N
        else:  # pragma: no cover
            raise ValueError("Bad dimension for q_sqrt: %s" %
                             str(q_sqrt.get_shape().ndims))
        if full_cov:
            fvar = fvar + tf.matmul(LTA, LTA, transpose_a=True)  # R x N x N
        else:
            fvar = fvar + tf.reduce_sum(tf.square(LTA), 1)  # R x N

    if not full_cov:
        fvar = tf.transpose(fvar)  # N x R

    return fmean, fvar  # N x R, R x N x N or N x R


# ----------------------------------------------------------------------------
############################ UNCERTAIN CONDITIONAL ###########################
# ----------------------------------------------------------------------------

@name_scope()
def uncertain_conditional(Xnew_mu, Xnew_var, feat, kern, q_mu, q_sqrt, *,
                          mean_function=None, full_cov_output=False, full_cov=False, white=False):
    """
    Calculates the conditional for uncertain inputs Xnew, p(Xnew) = N(Xnew_mu, Xnew_var).
    See ``conditional`` documentation for further reference.

    :param Xnew_mu: mean of the inputs, size N x Din
    :param Xnew_var: covariance matrix of the inputs, size N x Din x Din
    :param feat: gpflow.InducingFeature object, only InducingPoints is supported
    :param kern: gpflow kernel or ekernel object.
    :param q_mu: mean inducing points, size M x Dout
    :param q_sqrt: cholesky of the covariance matrix of the inducing points, size Dout x M x M
    :param full_cov_output: boolean wheter to compute covariance between output dimension.
                            Influences the shape of return value ``fvar``. Default is False
    :param white: boolean whether to use whitened representation. Default is False.

    :return fmean, fvar: mean and covariance of the conditional, size ``fmean`` is N x Dout,
            size ``fvar`` depends on ``full_cov_output``: if True ``f_var`` is N x Dout x Dout,
            if False then ``f_var`` is N x Dout
    """

    # TODO: Tensorflow 1.4 doesn't support broadcasting in``tf.matmul`` and
    # ``tf.matrix_triangular_solve``. This is reported in issue 216.
    # As a temporary workaround, we are using ``tf.einsum`` for the matrix
    # multiplications and tiling in the triangular solves.
    # The code that should be used once the bug is resolved is added in comments.

    if not isinstance(feat, InducingPoints):
        raise NotImplementedError

    if full_cov:
        # TODO: ``full_cov`` True would return a ``fvar`` of shape N x N x D x D,
        # encoding the covariance between input datapoints as well.
        # This is not implemented as this feature is only used for plotting purposes.
        raise NotImplementedError

    pXnew = Gaussian(Xnew_mu, Xnew_var)

    num_data = tf.shape(Xnew_mu)[0]  # number of new inputs (N)
    num_ind = tf.shape(q_mu)[0]  # number of inducing points (M)
    num_func = tf.shape(q_mu)[1]  # output dimension (D)

    q_sqrt_r = tf.matrix_band_part(q_sqrt, -1, 0)  # D x M x M

    eKuf = tf.transpose(expectation(pXnew, (kern, feat)))  # M x N (psi1)
    Kuu = feat.Kuu(kern, jitter=settings.numerics.jitter_level)  # M x M
    Luu = tf.cholesky(Kuu)  # M x M

    if not white:
        q_mu = tf.matrix_triangular_solve(Luu, q_mu, lower=True)
        Luu_tiled = tf.tile(Luu[None, :, :], [num_func, 1, 1])  # remove line once issue 216 is fixed
        q_sqrt_r = tf.matrix_triangular_solve(Luu_tiled, q_sqrt_r, lower=True)

    Li_eKuf = tf.matrix_triangular_solve(Luu, eKuf, lower=True)  # M x N
    fmean = tf.matmul(Li_eKuf, q_mu, transpose_a=True)

    eKff = expectation(pXnew, kern)  # N (psi0)
    eKuffu = expectation(pXnew, (kern, feat), (kern, feat))  # N x M x M (psi2)
    Luu_tiled = tf.tile(Luu[None, :, :], [num_data, 1, 1])  # remove this line, once issue 216 is fixed
    Li_eKuffu = tf.matrix_triangular_solve(Luu_tiled, eKuffu, lower=True)
    Li_eKuffu_Lit = tf.matrix_triangular_solve(Luu_tiled, tf.matrix_transpose(Li_eKuffu), lower=True)  # N x M x M
    cov = tf.matmul(q_sqrt_r, q_sqrt_r, transpose_b=True)  # D x M x M

    if mean_function is None or isinstance(mean_function, mean_functions.Zero):
        e_related_to_mean = tf.zeros((num_data, num_func, num_func), dtype=settings.float_type)
    else:
        # Update mean: \mu(x) + m(x)
        fmean = fmean + expectation(pXnew, mean_function)

        # Calculate: m(x) m(x)^T + m(x) \mu(x)^T + \mu(x) m(x)^T,
        # where m(x) is the mean_function and \mu(x) is fmean
        e_mean_mean = expectation(pXnew, mean_function, mean_function)  # N x D x D
        Lit_q_mu = tf.matrix_triangular_solve(Luu, q_mu, adjoint=True)
        e_mean_Kuf = expectation(pXnew, mean_function, (kern, feat))  # N x D x M
        # einsum isn't able to infer the rank of e_mean_Kuf, hence we explicitly set the rank of the tensor:
        e_mean_Kuf = tf.reshape(e_mean_Kuf, [num_data, num_func, num_ind])
        e_fmean_mean = tf.einsum("nqm,mz->nqz", e_mean_Kuf, Lit_q_mu)  # N x D x D
        e_related_to_mean = e_fmean_mean + tf.matrix_transpose(e_fmean_mean) + e_mean_mean

    if full_cov_output:
        fvar = (
                tf.matrix_diag(tf.tile((eKff - tf.trace(Li_eKuffu_Lit))[:, None], [1, num_func])) +
                tf.matrix_diag(tf.einsum("nij,dji->nd", Li_eKuffu_Lit, cov)) +
                # tf.matrix_diag(tf.trace(tf.matmul(Li_eKuffu_Lit, cov))) +
                tf.einsum("ig,nij,jh->ngh", q_mu, Li_eKuffu_Lit, q_mu) -
                # tf.matmul(q_mu, tf.matmul(Li_eKuffu_Lit, q_mu), transpose_a=True) -
                fmean[:, :, None] * fmean[:, None, :] +
                e_related_to_mean
        )
    else:
        fvar = (
                (eKff - tf.trace(Li_eKuffu_Lit))[:, None] +
                tf.einsum("nij,dji->nd", Li_eKuffu_Lit, cov) +
                tf.einsum("ig,nij,jg->ng", q_mu, Li_eKuffu_Lit, q_mu) -
                fmean ** 2 +
                tf.matrix_diag_part(e_related_to_mean)
        )

    return fmean, fvar
