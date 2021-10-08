import sys, os
sys.path.append('./')
import numpy as np
import torch
from torch_sqrtm import MatrixSquareRoot

from torch.optim import Adam
import time

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

torch_sqrtm = MatrixSquareRoot.apply

# ADMM
class G_admm():
    def __init__(self, X, K, TF = None, seed = 0, pre_cov = None):
        super(G_admm, self).__init__()
        # set random seed
        if seed is not None:
            torch.manual_seed(seed)

        # shape (ntimes, nsamples, ngenes)
        self.X = torch.FloatTensor(X).to(device)
        self.ntimes, self.nsamples, self.ngenes = self.X.shape
        
        if pre_cov is None:
            # shape (ntimes, nsamples, ngenes)
            self.epir_mean = self.X.mean(dim = 1, keepdim = True).expand(self.ntimes, self.nsamples, self.ngenes)
            X = self.X - self.epir_mean
            # (ntimes * nsamples, ngenes, ngenes)
            self.empir_cov = torch.bmm(X.reshape((self.ntimes * self.nsamples, self.ngenes, 1)), X.reshape((self.ntimes * self.nsamples, 1, self.ngenes)))
            # (ntimes, ngenes, ngenes)
            self.empir_cov = torch.sum(self.empir_cov.reshape((self.ntimes, self.nsamples, self.ngenes, self.ngenes)), dim = 1)/(self.nsamples - 1)

        else:
            self.empir_cov = pre_cov

        # shape (ntimes, ntimes)
        # self.kernel = ((np.ones(self.ntimes)/self.ntimes)*K)/np.sum(K,axis=0)
        self.weights = torch.FloatTensor(K).to(device)

        # mask matrix
        self.mask = 0
        if TF is not None:
            self.mask = torch.zeros(self.ngenes, self.ngenes).to(device)
            # mark probable interactions
            self.mask[TF, :] = 1
            self.mask[:, TF] = 1
            # element-wise reverse
            self.mask = 1 - self.mask        


    @staticmethod
    def neg_lkl_loss(theta, S):
        """\
        Description:
        --------------
            The negative log likelihood function
        Parameters:
        --------------
            theta:
                The estimated theta
            S:
                The empirical covariance matrix
        Return:
        --------------
            The negative log likelihood value
        """
        t1 = -1*torch.logdet(theta)
        t2 = torch.trace(torch.matmul(S, theta))
        return t1 + t2


    def train(self, t, max_iters = 50, n_intervals = 1, lamb = 2.1e-4, alpha = 1, rho = None, beta = 0, theta_init_offset = 0.1):
        # kernel function
        w = self.weights[t,:][:,None, None]
        assert (w.sum() - 1).abs() < 1e-6

        # weight average of empirical covariance matrix, [ngenes, ngenes]
        empir_cov_ave = torch.sum(w * self.empir_cov, dim = 0)
        # initialize
        Z = torch.diag_embed(1/(torch.diagonal(empir_cov_ave, offset=0, dim1=-2, dim2=-1) + theta_init_offset))
        # positive definite matrix
        ll = torch.cholesky(Z)
        Z = torch.matmul(ll, ll.transpose(-1, -2))
        
        U = torch.zeros(Z.shape).to(device)
        I = torch.eye(Z.shape[0]).to(device)
        zero = torch.Tensor([0]).to(device)

        it = 0
        if rho is None:
            updating_rho = True
            rho = 1.7
        else:
            updating_rho = False
          
        while(it < max_iters): 
            # Primal
            Y = U - Z + empir_cov_ave/rho # (ngenes, ngenes)
            theta = - 0.5 * Y + torch_sqrtm(Y.t() @ Y * 0.25 + I/rho)
            Z_pre = Z.detach().clone()
            # over-relaxation
            theta = alpha * theta + (1 - alpha) * Z_pre
            Z = torch.sign(theta + U) * torch.max((rho * (theta + U).abs() - lamb)/(rho + beta * self.mask), zero)
            assert Z.shape == (self.ngenes, self.ngenes)

            # Dual
            U = U + theta - Z

            # calculate residual
            primal_residual = torch.sqrt((theta - Z).pow(2).sum())
            dual_residual = rho * torch.sqrt((Z - Z_pre).pow(2).sum())
            
            # updating rho
            if updating_rho:
                if primal_residual > 10 * dual_residual:
                    rho =  rho * 2
                elif dual_residual > 10 * primal_residual:
                    rho = rho / 2
            # free-up memory
            del Z_pre
            # Stopping criteria
            if (it + 1) % n_intervals == 0:
                # calculate duality gap
                # loss = self.neg_lkl_loss(theta, empir_cov_ave) + lamb * Z.abs().sum() + beta * (self.mask * Z).pow(2).sum()
                # primal_val = loss  + rho/2 * (theta - Z).pow(2).sum()
                # dual_val = loss + rho/2 * (theta - Z + U).pow(2).sum() - rho/2 * U.pow(2).sum()
                # duality_gap = primal_val - dual_val

                # can be simplified
                duality_gap = rho * torch.trace(U.T @ (Z - theta))
                print("n_iter: {}, duality gap: {:.4e}, primal residual: {:.4e}, dual residual: {:4e}".format(it+1, duality_gap.item(), primal_residual.item(), dual_residual.item()))
                # duality gap is reducing extremely fast, and even duality gap reduce sometime, dual residual may explod
                # if duality_gap.abs() < 1e-8:
                #     break

                # epsilon_abs = 1e-4
                # epsilon_rel = 1e-4
                # primal_eps = np.sqrt(theta.shape[0]) * epsilon_abs + epsilon_rel * max(theta.pow(2).sum().sqrt(), Z.pow(2).sum().sqrt())
                # dual_eps = np.sqrt(theta.shape[0]) * epsilon_abs + epsilon_rel * U.pow(2).sum().sqrt()
                # print("primal_eps: {:.4e}, dual_eps: {:.4e}".format(primal_eps, dual_eps))
                primal_eps = 1e-6
                dual_eps = 1e-6
                if (primal_residual < primal_eps) and (dual_residual < dual_eps):
                    break

            it += 1
        
        loss1 = self.neg_lkl_loss(Z, empir_cov_ave)
        loss2 = Z.abs().sum()
        loss3 = (self.mask * Z).pow(2).sum()
        print("Final: loss1: {:.5f}, loss2: {:.5f}, loss3: {:.5f}".format(loss1.item(), loss2.item(), loss3.item()))

        return Z.cpu().numpy()


class G_admm_batch():
    def __init__(self, X, K, TF = None, seed = 0, method = 0, pre_cov = None):
        super(G_admm_batch, self).__init__()
        # set random seed
        if seed is not None:
            torch.manual_seed(seed)

        # shape (ntimes, nsamples, ngenes)
        self.X = torch.FloatTensor(X)
        self.ntimes, self.nsamples, self.ngenes = self.X.shape

        if pre_cov is None:
            # shape (ntimes, nsamples, ngenes)
            self.epir_mean = self.X.mean(dim = 1, keepdim = True)
            X = self.X - self.epir_mean
            # (ntimes * nsamples, ngenes, ngenes)
            self.empir_cov = torch.bmm(X.reshape((self.ntimes * self.nsamples, self.ngenes, 1)), X.reshape((self.ntimes * self.nsamples, 1, self.ngenes)))
            # (ntimes, ngenes, ngenes)
            self.empir_cov = torch.sum(self.empir_cov.reshape((self.ntimes, self.nsamples, self.ngenes, self.ngenes)), dim = 1)/(self.nsamples - 1)
        else:
            self.empir_cov = pre_cov

        # shape (ntimes, ntimes)
        self.weights = torch.FloatTensor(K)

        # shape (total input dim(=ntimes), ntimes, ngnes,ngens) > (total input dim(=ntimes), ngnes,ngens) "weighted avg."
        assert torch.all(torch.sum(self.weights,dim=1) - 1 < 1e-6)
        self.w_empir_cov = torch.sum((self.weights[:,:,None,None]*self.empir_cov[None,:,:,:]),dim=1).to(device)

        # method 1 (cal entire sample covariance matrix > assigning weights)
        self.X_all = self.X.reshape(1, self.ntimes * self.nsamples, self.ngenes)
        self.epir_mean_all = self.X_all.mean(dim = 1, keepdim = True).expand(1, self.ntimes * self.nsamples, self.ngenes)
        X_all = self.X_all - self.epir_mean_all
        self.empir_cov_all = torch.bmm(X_all.reshape((self.ntimes * self.nsamples, self.ngenes, 1)), X_all.reshape((self.ntimes * self.nsamples, 1, self.ngenes)))
        
        self.empir_cov_all = torch.sum(self.empir_cov_all.reshape(self.ntimes, self.nsamples, self.ngenes, self.ngenes), dim=1)/(self.nsamples-1)
        self.w_empir_cov_all = torch.sum((self.weights[:,:,None,None] * self.empir_cov_all[None,:,:,:]), dim=1)

        if method == 1:
            self.w_empir_cov = self.w_empir_cov_all.to(device)
        
        # mask matrix (ntimes, ngenes, ngenes)
        if TF is not None:
            self.mask = torch.zeros(self.ngenes, self.ngenes).to(device)
            # mark probable interactions
            self.mask[TF, :] = 1
            self.mask[:, TF] = 1
            # element-wise reverse
            self.mask = 1 - self.mask
            self.mask = self.mask.expand(self.ntimes, self.ngenes, self.ngenes)   
        else:
            self.mask = torch.FloatTensor([0]).to(device) 

    @staticmethod
    def neg_lkl_loss(thetas, S):
        """\
        Description:
        --------------
            The negative log likelihood function
        Parameters:
        --------------
            theta:
                The estimated theta
            S:
                The empirical covariance matrix
        Return:
        --------------
            The negative log likelihood value
        """
        # logdet works for batches of matrices, give a high dimensional data
        t1 = -1*torch.logdet(thetas)
        t2 = torch.stack([torch.trace(mat) for mat in torch.bmm(S, thetas)])
        return t1 + t2


    def train(self, max_iters = 50, n_intervals = 1, lamb = 2.1e-4, alpha = 1, rho = 1, beta = 0, theta_init_offset = 0.1):
        
       # initialize
        Z = torch.diag_embed(1/(torch.diagonal(self.w_empir_cov, offset=0, dim1=-2, dim2=-1) + theta_init_offset))
        # positive definite matrix
        ll = torch.cholesky(Z)
        Z = torch.matmul(ll, ll.transpose(-1, -2))
        del ll
        U = torch.zeros(Z.shape).to(device)
        I = torch.eye(self.ngenes).expand(Z.shape).to(device)

        it = 0
        if rho is None:
            updating_rho = True
            # rho of the shape (ntimes, 1, 1)
            rho = 1.7 * torch.ones((Z.shape[0], 1, 1)).to(device) 
        else:
            rho = torch.FloatTensor([rho] * Z.shape[0])[:, None, None].to(device)
            updating_rho = False

        while(it < max_iters): 
            # Primal 
            Y = U - Z + self.w_empir_cov/rho    # (ntimes, ngenes, ngenes)
            thetas = - 0.5 * Y + torch.stack([torch_sqrtm(mat) for mat in (torch.transpose(Y,1,2) @ Y * 0.25 + I/rho)])
            Z_pre = Z.detach().clone()
            # over-relaxation
            thetas = alpha * thetas + (1 - alpha) * Z_pre            
            Z = torch.sign(thetas + U) * torch.max((rho * (thetas + U).abs() - lamb)/(rho + beta * self.mask), torch.Tensor([0]).to(device))
            assert Z.shape == (self.ntimes, self.ngenes, self.ngenes)

            # Dual
            U = U + thetas - Z

            # calculate residual
            # primal_residual and dual_residual of the shape (ntimes, 1, 1)
            primal_residual = torch.sqrt((thetas - Z).pow(2).sum(1).sum(1))
            dual_residual = rho.squeeze() * torch.sqrt((Z - Z_pre).pow(2).sum(1).sum(1))

            # updating rho, rho should be of shape (ntimes, 1, 1)
            if updating_rho:
                mask_inc = (primal_residual > 10 * dual_residual)
                rho[mask_inc, :, :] = rho[mask_inc, :, :] * 2
                mask_dec = (dual_residual > 10 * primal_residual)
                rho[mask_dec, :, :] = rho[mask_dec, :, :] / 2
            
            # print(rho.squeeze())
            # free-up memory
            del Z_pre
            
            # Stopping criteria
            if (it + 1) % n_intervals == 0:
                # calculate sum of all duality gap
                # loss = self.neg_lkl_loss(thetas, self.w_empir_cov).sum() + lamb * Z.abs().sum() + beta * (self.mask * Z).pow(2).sum()
                # primal_val = loss  + rho/2 * (thetas - Z).pow(2).sum()
                # dual_val = loss + rho/2 * (thetas - Z + U).pow(2).sum() - rho/2 * U.pow(2).sum()
                # duality_gap = primal_val - dual_val

                # simplify min of all duality gap
                duality_gap = rho.squeeze() * torch.stack([torch.trace(mat) for mat in torch.bmm(U.permute(0,2,1), Z - thetas)])
                duality_gap = duality_gap.abs()
                print("n_iter: {}, duality gap: {:.4e}, primal residual: {:.4e}, dual residual: {:4e}".format(it+1, duality_gap.max().item(), primal_residual.max().item(), dual_residual.max().item()))
                
                # if duality_gap < 1e-8:
                #     break
                primal_eps = 1e-6
                dual_eps = 1e-6
                if (primal_residual.max() < primal_eps) and (dual_residual.max() < dual_eps):
                    break                
            it += 1
        del thetas, U, I, Y
        loss1 = self.neg_lkl_loss(Z, self.w_empir_cov).sum()
        loss2 = Z.abs().sum()
        loss3 = (self.mask * Z).pow(2).sum()
        print("Final: loss1: {:.5f}, loss2: {:.5f}, loss3: {:.5f}".format(loss1.item(), loss2.item(), loss3.item()))   

        return Z.cpu().numpy()


class G_admm_minibatch():
    def __init__(self, X, K, TF = None, seed = 0, pre_cov = None, batchsize = None):
        super(G_admm_minibatch, self).__init__()
        # set random seed
        if seed is not None:
            torch.manual_seed(seed)

        # shape (ntimes, nsamples, ngenes)
        self.X = torch.FloatTensor(X)
        self.ntimes, self.nsamples, self.ngenes = self.X.shape
        
        # calculate batchsize
        if batchsize is None:
            self.batchsize = int(self.ntimes/10)
        else:
            self.batchsize = batchsize
        # calculate empirical covariance matrix
        if pre_cov is None:
            # shape (ntimes, nsamples, ngenes)
            self.epir_mean = self.X.mean(dim = 1, keepdim = True)
            X = self.X - self.epir_mean
            # (ntimes * nsamples, ngenes, ngenes)
            self.empir_cov = torch.bmm(X.reshape((self.ntimes * self.nsamples, self.ngenes, 1)), X.reshape((self.ntimes * self.nsamples, 1, self.ngenes)))
            # (ntimes, ngenes, ngenes)
            self.empir_cov = torch.sum(self.empir_cov.reshape((self.ntimes, self.nsamples, self.ngenes, self.ngenes)), dim = 1)/(self.nsamples - 1)
        else:
            self.empir_cov = pre_cov

        # weight kernel function, shape (ntimes, ntimes)
        self.weights = torch.FloatTensor(K)
        # weighted average of empricial covariance matrix
        assert torch.all(torch.sum(self.weights,dim=1) - 1 < 1e-6)
        self.w_empir_cov = torch.sum((self.weights[:,:,None,None]*self.empir_cov[None,:,:,:]),dim=1) 
        # store the result
        self.thetas = np.zeros((self.ntimes, self.ngenes, self.ngenes))
        
        # mask matrix (ntimes, ngenes, ngenes)
        if TF is not None:
            self.mask = torch.zeros(self.ngenes, self.ngenes)
            # mark probable interactions
            self.mask[TF, :] = 1
            self.mask[:, TF] = 1
            # element-wise reverse
            self.mask = 1 - self.mask
            self.mask = self.mask.expand(self.ntimes, self.ngenes, self.ngenes) 
        else:
            self.mask = torch.FloatTensor([0])  

    @staticmethod
    def neg_lkl_loss(thetas, S):
        """\
        Description:
        --------------
            The negative log likelihood function
        Parameters:
        --------------
            theta:
                The estimated theta
            S:
                The empirical covariance matrix
        Return:
        --------------
            The negative log likelihood value
        """
        # logdet works for batches of matrices, give a high dimensional data
        t1 = -1*torch.logdet(thetas)
        t2 = torch.stack([torch.trace(mat) for mat in torch.bmm(S, thetas)])
        return t1 + t2


    def train(self, max_iters = 50, n_intervals = 1, lamb = 2.1e-4, alpha = 1, rho = 1, beta = 0, theta_init_offset = 0.1):
        n_batches = int(np.ceil(self.ntimes/self.batchsize))
        for batch in range(n_batches):
            print("start running batch " + str(batch))
            start_time = time.time()
            # select a minibatch, and load to cuda
            start_idx = batch * self.batchsize
            if batch < n_batches - 1:
                end_idx = (batch + 1) * self.batchsize
                w_empir_cov = self.w_empir_cov[start_idx:end_idx, :, :].to(device)
                if self.mask.shape[0] == self.ntimes:
                    mask = self.mask[start_idx:end_idx, :, :].to(device)
                else:
                    mask = self.mask.to(device)
            else:
                w_empir_cov = self.w_empir_cov[start_idx:, :, :].to(device)
                if self.mask.shape[0] == self.ntimes:
                    mask = self.mask[start_idx:, :, :].to(device)
                else:
                    mask = self.mask.to(device)
            # initialize mini-batch, Z of the shape (batch_size, ngenes, ngenes)
            Z = torch.diag_embed(1/(torch.diagonal(w_empir_cov, offset=0, dim1=-2, dim2=-1) + theta_init_offset))
            # make Z positive definite matrix
            ll = torch.cholesky(Z)
            Z = torch.matmul(ll, ll.transpose(-1, -2))
            U = torch.zeros(Z.shape).to(device)
            I = torch.eye(self.ngenes).expand(Z.shape).to(device)

            it = 0
            # hyper-parameter for batches
            if rho is None:
                updating_rho = True
                # rho of the shape (ntimes, 1, 1)
                b_rho = torch.ones((Z.shape[0], 1, 1)).to(device) * 1.7
            else:
                b_rho = torch.FloatTensor([rho] * Z.shape[0])[:, None, None].to(device)
                updating_rho = False
            b_alpha = alpha 
            b_beta = beta
            b_lamb = lamb
            while(it < max_iters): 
                # Primal 
                Y = U - Z + w_empir_cov/b_rho    # (ntimes, ngenes, ngenes)
                thetas = - 0.5 * Y + torch.stack([torch_sqrtm(mat) for mat in (torch.transpose(Y,1,2) @ Y * 0.25 + I/b_rho)])
                Z_pre = Z.detach().clone()
                # over-relaxation
                thetas = b_alpha * thetas + (1 - b_alpha) * Z_pre            
                Z = torch.sign(thetas + U) * torch.max((b_rho * (thetas + U).abs() - b_lamb)/(b_rho + b_beta * mask), torch.Tensor([0]).to(device))

                # Dual
                U = U + thetas - Z

                # calculate residual
                # primal_residual and dual_residual of the shape (ntimes, 1, 1)
                primal_residual = torch.sqrt((thetas - Z).pow(2).sum(1).sum(1))
                dual_residual = b_rho.squeeze() * torch.sqrt((Z - Z_pre).pow(2).sum(1).sum(1))

                # updating rho, rho should be of shape (ntimes, 1, 1)
                if updating_rho:
                    mask_inc = (primal_residual > 10 * dual_residual)
                    b_rho[mask_inc, :, :] = b_rho[mask_inc, :, :] * 2
                    mask_dec = (dual_residual > 10 * primal_residual)
                    b_rho[mask_dec, :, :] = b_rho[mask_dec, :, :] / 2
                
                # print(rho.squeeze())
                # free-up memory
                del Z_pre
                
                # Stopping criteria
                if (it + 1) % n_intervals == 0:
                    # calculate sum of all duality gap
                    # loss = self.neg_lkl_loss(thetas, w_empir_cov).sum() + b_lamb * Z.abs().sum() + b_beta * (self.mask * Z).pow(2).sum()
                    # primal_val = loss  + rho/2 * (thetas - Z).pow(2).sum()
                    # dual_val = loss + rho/2 * (thetas - Z + U).pow(2).sum() - rho/2 * U.pow(2).sum()
                    # duality_gap = primal_val - dual_val

                    # simplify min of all duality gap
                    duality_gap = b_rho.squeeze() * torch.stack([torch.trace(mat) for mat in torch.bmm(U.permute(0,2,1), Z - thetas)])
                    duality_gap = duality_gap.abs()
                    print("n_iter: {}, duality gap: {:.4e}, primal residual: {:.4e}, dual residual: {:4e}".format(it+1, duality_gap.max().item(), primal_residual.max().item(), dual_residual.max().item()))
                    
                    # if duality_gap < 1e-8:
                    #     break
                    primal_eps = 1e-6
                    dual_eps = 1e-6
                    if (primal_residual.max() < primal_eps) and (dual_residual.max() < dual_eps):
                        break                
                it += 1
            
            loss1 = self.neg_lkl_loss(Z, w_empir_cov).sum()
            loss2 = Z.abs().sum()
            loss3 = (mask * Z).pow(2).sum()
            print("Batch loss: loss1: {:.5f}, loss2: {:.5f}, loss3: {:.5f}".format(loss1.item(), loss2.item(), loss3.item()))  
            # store values
            if batch < n_batches - 1:
                self.thetas[start_idx:end_idx] = Z.detach().cpu().numpy()
            else:
                self.thetas[start_idx:] = Z.detach().cpu().numpy()
            del thetas, U, I, Y, ll, Z

            print("Finished running batch {:d}, running time: {:.2f} sec".format(batch, time.time() - start_time))

        return self.thetas

