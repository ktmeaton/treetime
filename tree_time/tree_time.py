"""
Class, which contains methods to optimize branch lengths given the time
constraints set to leaves
"""
# import tree_anc as ta
from __future__ import print_function, division
from .tree_anc import TreeAnc
import numpy as np
from Bio import AlignIO
import datetime
from scipy import stats
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from scipy import optimize as sciopt

class DateConversion(object):

    """
    Small container class to store parameters to convert between branch length
    as it is used in ML computations and the dates of the nodes.
    It is assumed that the conversion formula is 'length = k*date + b'
    """
    def __init__(self):

        self.slope = 0
        self.intersect = 0
        self.r_val = 0
        self.pi_val = 0
        self.sigma = 0

    @classmethod
    def from_tree(cls, t):
        dates = []
        for node in t.find_clades():
            if node.raw_date is not None:
                dates.append((node.raw_date, node.dist2root))
        dates = np.array(dates)
        cls.slope,\
            cls.intersect,\
            cls.r_val,\
            cls.pi_val,\
            cls.sigma = stats.linregress(dates[:, 0], dates[:, 1])
        return cls

        # set dates to the internal nodes

        self._ml_t_init(gtr)

    def get_branch_len(self, date1, date2):
        """
        Compute branch length given the dates of the two nodes.

        Args:
         - date1 (int): date of the first node (days before present)
         - date2 (int): date of the second node (days before present)

        Returns:
         - branch length (double): Branch length, assuming that the dependence
         between the node date and the node depth in the the tree is linear.
        """
        return abs(date1 - date2) * self.slope

    def get_date(self, abs_t):
        """
        Get the approximate date of the tree node, assuming that the
        dependence between the node date and the node depth int the tree is
        linear.

        Args:
         - node(Phylo.Tree.Clade): node of the tree. Must be from the TreeAnc
         class (or its derivative), to contain the necessary attributes (
            dist2root).

        """
        year = (self.intersect - abs_t) / self.slope
        if year < 0:
            print ("Warning: got the negative date! Returning the inverse.")
            year = abs(year)
        return year


class TreeTime(TreeAnc, object):

    """
    TreeTime is the main class to perform the optimization of the node
    positions  given the temporal constraints of (some) nodes and leaves.
    To se how to use it, please refer to the examples section.
    """

    MIN_T = -1e5
    MAX_T = 1e5
    MIN_LOG = -1000

    def __init__(self, tree):
        super(TreeTime, self).__init__(tree)
        self.date2dist = None  # we do not know anything about the conversion
        self.tree_file = ""
        self.max_node_abs_t = 0.0


    @property
    def average_branch_len(self):
        tot_branches = (self.tree.count_terminals() -1)* 2
        tot_len = self.tree.total_branch_length ()      
        return tot_len/tot_branches
    

    @classmethod
    def from_files(cls, tree_file, aln_file, **kwargs):
        """
        """
        # parsing kwargs:
        if 'tree_fmt' in kwargs:
            tree_fmt = kwargs['tree_fmt']
        else:
            print ("Trying to read tree using default tree format")
            tree_fmt = 'newick'
        if 'aln_fmt' in kwargs:
            aln_fmt = kwargs['aln_fmt']
        else:
            print ("Trying to read alignment using default format (fasta)")
            aln_fmt = 'fasta'

        tree = cls.from_file(tree_file, tree_fmt)
        tree.tree_file = tree_file

        aln = AlignIO.read(aln_file, aln_fmt)
        tree.set_seqs_to_leaves(aln)

        if 'dates_file' in kwargs:
            dates_file = kwargs['dates_file']
            d_dic = tree._read_dates_file(dates_file)
            tree._set_dates_to_all_nodes(d_dic)
        return tree

    def _read_dates_file(self, inf, **kwargs):
        """
        Read dates from the file into python dictionary. The input file should
        be in csv format 'node name, date'. The date will be converted to the
        datetime object and added to the dictionary {node name: datetime}

        Args:
         - inf(str): path to input file

        KWargs:
         - verbose(int): how verbose should the output be

        Returns:
         - dic(dic): dictionary  {NodeName: Date as datetime object}
        """

        def str_to_date(instr):
            """
            Convert input string to datetime object.
    
            Args:
             - instr (str): input string. Accepts one of the formats:
             {YYYY.MM.DD, YYYY.MM, YYYY}.
    
            Returns:
             - date (datetime.datetime): parsed date object. If the parsing
             failed, None is returned
            """
            # import ipdb; ipdb.set_trace()
            try:
                date = datetime.datetime.strptime(instr, "%Y.%m.%d")
            except ValueError:
                date = None
            if date is not None:
                return date
    
            try:
                date = datetime.datetime.strptime(instr, "%Y.%m")
            except ValueError:
                date = None
    
            if date is not None:
                return date
    
            try:
                date = datetime.datetime.strptime(instr, "%Y")
            except ValueError:
                date = None
    
            return date

        if 'verbose' in kwargs:
            verbose = kwargs['verbose']
        else:
            verbose = 10

        if verbose > 3:
            print ("Reading datetime info for the tree nodes...")
        with open(inf, 'r') as finf:
            all_ss = finf.readlines()
        if verbose > 5:
            print ("Loaded %d lines form dates file" % len(all_ss))
        try:
            dic = {s.split(',')[0]: str_to_date(s.split(',')[1].strip())
                   for s in all_ss if not s.startswith("#")}
            if verbose > 3:
                print ("Parsed data in %d lines of %d input, %d corrupted"
                       % (len(dic), len(all_ss), len(all_ss) - len(dic)))
            return dic
        except ValueError:
            # unable to read all dates, the file is corrupted - go one by one
            print ("Unable to perform parsing of the dates file, file is "
                   "corrupted. Return empty dictionary.")
            return {}

    def _set_dates_to_all_nodes(self, dates_dic, reroot=True):
        """
        Set the time information to all nodes.
        Gets the datetime object of the nodes specified, calculate the time
        before present  (in days) for the nodes and sets this parameter (as
            int) to the node.date attribute.
        Args:
         - dates_dic(dic): dictionary with datetime informationfor nodes.
         Format: {node name: datetime object}

         -reroot(bool, defalut True): whether to reroot to the oldest branch 
         after the dates are assigned to al nodes

        """
        now = datetime.datetime.now()

        for node in self.tree.find_clades(order='preorder'):
            if node.name in dates_dic \
                    and dates_dic[node.name] is not None:
                days_before_present = (now - dates_dic[node.name]).days
                if days_before_present < 0:
                    print ("Cannot set the date! the specified date is later "
                        " than today")
                    continue
                node.raw_date = days_before_present
            else:
                node.raw_date = None
        self.reroot_to_oldest()

    def reroot_to_oldest(self):
        """
        Set the root to the oldest node
        """
        # for now, we just reroot the to the most ancient node. Later,
        # it should be done in a cleverer way.

        self.tree.root_with_outgroup(sorted(self.tree.get_terminals(),
                                            key=lambda x: x.raw_date)[-1])
        self.tree.root.raw_date = None
        # fix tree lengths, etc
        self._add_node_params()

    def init_date_constraints(self, gtr):
        """
        Get the conversion coefficients between the dates and the branch
        lengths as they are used in ML computations. The conversion formula is
        assumed to be 'length = k*date + b'. For convenience, these
        coefficients as well as regression parameters are stored in the
        dates2dist object.

        Note: that tree must have dates set to all nodes before calling this
        function. (The latter is accomplished by calling load_dates func).
        """

        self.date2dist = DateConversion.from_tree(self.tree)

        # set dates to the internal nodes

        self._ml_t_init(gtr)

    def _make_branch_len_interpolator(self, node, gtr, n=10):
        """
        makes an interpolation object for propability of branch length
        requires previous branch_length optimization and initialization of the 
        temporal constraints to account for short branches.
        """
        
        if node.up is None:
            node.branch_neg_log_prob = None
            return None

        parent = node.up
        prof_p = parent.profile
        prof_ch = node.profile
        
        if node.branch_length < 1e-5:
            # protection against zero value in the tree depth. 
            # if so, use 0.01 which is (roughly) 1% diff between sequences
            sigma = np.max([0.01, 0.1 * self.max_node_abs_t])
            # allow variation up to 10% of the max tree depth
            grid = sigma * (np.linspace(0.0, 1.0 , n)**2)
        else:
            
            sigma = np.max([self.average_branch_len, node.branch_length])
            
            grid_left = node.branch_length * (1 - np.linspace(1, 0.0, n / 2)**2)
            grid_right = node.branch_length + (
                    3 * sigma * (np.linspace(0, 1, n / 2) ** 2) )
            grid = np.concatenate((grid_left,grid_right))
            
        grid = np.concatenate(([self.MIN_T, -1e-30], 
                              grid,
                              [self.MAX_T])
                             )
        logprob = np.concatenate([[0, 0], [gtr.prob_t(prof_p, prof_ch, t_, return_log=True) for t_ in grid[2:-1]], [0]])
        logprob[((0,-1),)] = self.MIN_LOG
        logprob[((1,-2),)] = self.MIN_LOG / 2
        logprob *= -1.0        

        node.branch_neg_log_prob = interp1d(grid, logprob, kind='linear')

    def _ml_t_init(self, gtr):
        """
        Initialize the tree nodes for ML computations with temporal
        constraints.
        Set the absolute positions for the nodes, init grid and constraints,
        set sequence profiles to the nodes.

        Args:
         - gtr(GTR): Evolutionary model, required to compute some node
         parameters.
        """
        if self.date2dist is None:
            print ("error")
            return
        for node in self.tree.find_clades():
            # node is constrained
            if node.raw_date is not None:
             
                # set the absolute time according to the date info
                node.abs_t = node.raw_date * self.date2dist.slope + \
                    self.date2dist.intersect          
                
                # probability is the delta-function
                grid = np.concatenate(([self.MIN_T], 
                    node.abs_t * np.array([1 - 1e-10, 1, 1 + 1e-10]), 
                    [self.MAX_T]))
                
                node.neg_log_prob = interp1d(grid, 
                    -1 * np.array([self.MIN_LOG, 
                            self.MIN_LOG / 2, 
                            np.log(1e10), 
                            self.MIN_LOG/2, 
                            self.MIN_LOG]), kind='linear')
                
            # unconstrained node 
            else:
                node.abs_t = node.dist2root  # not corrected!
                # if there are no constraints - log_prob will be set on-the-fly
                node.neg_log_prob = None
            
            # set max tree depth
            if node.abs_t > self.max_node_abs_t:
                self.max_node_abs_t = node.abs_t
            
            # make interpolation object for branch lengths 
            self._make_branch_len_interpolator(node, gtr, n=25)

            # log-scale likelihood prefactor
            node.ml_t_prefactor = 0.0
            # set the profiles in the eigenspace of the GTR matrix
            # in the following, we only use the prf_l and prf_r (left and right 
            # profiles in the matrix eigenspace)
            self._set_rotated_profiles(node, gtr)
                

    def _min_interp(self, interp_object):
        
        #import ipdb; ipdb.set_trace()

        return interp_object.x[interp_object(interp_object.x).argmin()]
        #opt_ = sciopt.minimize_scalar(interp_object, 
        #    bounds=[-2 * self.max_node_abs_t, 2 * self.max_node_abs_t],
        #    method='brent')
        #return opt_.x
        #if opt_.success != True:
        #    return None
        
        #else:
        #    return opt_.x

    def _find_node_opt_pos(self, node):
        if not hasattr(node, "neg_log_prob") or node.neg_log_prob is None:
            return None
        return self._min_interp(node.neg_log_prob)
    
    def _make_node_grid(self, 
                opt, 
                grid_size=100, 
                variance=0.25):
        scale = self.max_node_abs_t * variance
        # quadratic grid - fine around opt, sparse at the edges
        grid_root = opt - scale * (np.linspace(1, 1e-5, grid_size / 2 - 1)**2)
        grid_leaves = opt + scale * (np.linspace(0, 1, grid_size / 2)**2)

        grid = np.concatenate(([self.MIN_T],
            grid_root,
            grid_leaves,
            [self.MAX_T]))

        return grid

    def _convolve(self, 
                     src_neglogprob, 
                     src_branch_neglogprob, 
                     inverse_time,
                     grid_size=100):
        """
        Compute the convolution of parent (target) and child (source) 
        nodes inverse log-likelihood distributions. 
        Take the source node log-LH distribution, extracts its grid. Based on 
        the brach length probability distrribution (also inverse log-LH), find 
        approximate position of the target node. Make the grid for the target 
        node, and for each point of this newly generated grid, compute the 
        convolution over all possible positions of the source node. 
        
        Args:
         
        - src_neglogprob (scipy.interpolate.interp1d): inverse log-LH 
         distribution of the node to be integrated, represented as scipy 
         interpolation object
         
        - src_branch_neglogprob(scipy.interpolate.interp1d): inverse log-LH 
         distribution of the branch lenghts between the two nodes, represented 
         as scipy interpolation object

         - inverse_time (bool): Whether the time should be inversed. 
         True if we go from leaves to root (against absolute time scale), and 
         the convolution is computed over positions of the child node. 
         False if the messages are propagated from root towards leaves (the same 
         direction as the absolute time axis), and the convolution is being 
         computed over the position of the parent node

         - grid_size (int): size of the grid for the target node positions.
        """
        opt_source_pos = self._min_interp(src_neglogprob)
        opt_branch_len = sciopt.minimize_scalar(src_branch_neglogprob,
            bounds=[0.0, 2 * self.max_node_abs_t],
            method='bounded')
        if opt_branch_len.success != True:
            opt_branch_len = 0.0
        else:
            opt_branch_len = opt_branch_len.x

        # either we have assessed the node optimal position 
        # and can make suggestions about parent opt position,
        # or both positions remain undefined
        if opt_source_pos is not None:
            opt_target_pos = opt_source_pos - opt_branch_len
        else:
            opt_target_pos = None
        source_grid = src_neglogprob.x 
        target_grid = self._make_node_grid(opt_target_pos, 
                grid_size, 
                variance=0.25) #parent_var / self.max_node_abs_t)
        grid2D = source_grid[:, None] - target_grid
        
        # if we go along the time axis, the scr node will be earlier in time, 
        # so to get the positive branch lengths in the right direction, 
        # we should inverse the grid
        if inverse_time == False:
            grid2D *= -1.0

        grid2D[grid2D<self.MIN_T] = self.MIN_T
        grid2D[grid2D>self.MAX_T] = self.MAX_T
        
        logprob2D = src_branch_neglogprob(grid2D)
        logprob2D[:,((1,-2),)] = -1 * self.MIN_LOG / 2
        logprob2D[((1,-2),), :] = -1 * self.MIN_LOG / 2
        logprob2D[:,((0,-1),)] = -1 * self.MIN_LOG 
        logprob2D[((0,-1),), :] = -1 * self.MIN_LOG

        prob2D = np.exp(-1 * logprob2D) # real probabilities

        # compute convolution
        dx = np.diff(source_grid, axis=0)
        prob_source = np.exp(-1 * src_neglogprob(source_grid))
        d_conv = (prob2D.T * prob_source)
        conv = (0.5 * (d_conv[:, 1:] + d_conv[:, :-1]) * dx).sum(1)
        
        p_logprob = np.log(conv + 1e-100) # grid already contains  far points
        p_logprob[((0,-1),)] = self.MIN_LOG
        p_logprob[((1,-2),)] = self.MIN_LOG / 2
        
        target_neglogprob = interp1d(target_grid, -1 * p_logprob, kind='linear')
        return target_neglogprob

    def _parent_neg_log_prob(self, node, grid_size=100):
        opt_node_pos = self._find_node_opt_pos(node)
        opt_branch_len = sciopt.minimize_scalar(node.branch_neg_log_prob,
            bounds=[0.0, 2 * self.max_node_abs_t],
            method='bounded')

        if opt_branch_len.success != True:
            opt_branch_len = 0.0
        else:
            opt_branch_len = opt_branch_len.x

        # either we have assessed the node optimal position 
        # and can make suggestions about parent opt position,
        # or both positions remain undefined
        if opt_node_pos is not None:
            opt_parent_pos = opt_node_pos - opt_branch_len
        else:
            opt_parent_pos = None

        node_grid = node.neg_log_prob.x #self._make_node_grid(opt_node_pos, grid_size)
        #parent_var = node_grid[-2] + 5 * opt_branch_len - node_grid[1]
        
        parent_grid = self._make_node_grid(opt_parent_pos, 
                grid_size, 
                variance=0.25) #parent_var / self.max_node_abs_t)
        

        grid2D = node_grid[:, None] - parent_grid
        grid2D[grid2D<self.MIN_T] = self.MIN_T
        grid2D[grid2D>self.MAX_T] = self.MAX_T
        
        logprob2D = node.branch_neg_log_prob(grid2D)
        logprob2D[:,((1,-2),)] = -1 * self.MIN_LOG / 2
        logprob2D[((1,-2),), :] = -1 * self.MIN_LOG / 2
        logprob2D[:,((0,-1),)] = -1 * self.MIN_LOG 
        logprob2D[((0,-1),), :] = -1 * self.MIN_LOG

        prob2D = np.exp(-1 * logprob2D) # real probabilities

        # compute convolution
        dx = np.diff(node_grid, axis=0)
        prob_node = np.exp(-1 * node.neg_log_prob(node_grid))
        d_conv = (prob2D.T * prob_node)
        conv = (0.5 * (d_conv[:, 1:] + d_conv[:, :-1]) * dx).sum(1)
        
        p_logprob = np.log(conv + 1e-100) # grid already contains  far points
        p_logprob[((0,-1),)] = self.MIN_LOG
        p_logprob[((1,-2),)] = self.MIN_LOG / 2
        
        parent_neg_log_prob = interp1d(parent_grid, -1 * p_logprob, kind='linear')
        return parent_neg_log_prob

    def _multiply_dists(self, interps, prefactors, grid_size=100):
        """
        Multiply two distributions of inverse log-likelihoods, 
        represented as interpolation objects. Takes array of interpolation objects, 
        extracts the grid, builds the new grid for the resulting distribution, 
        performs multiplication on a new grid.
        Args:
         
         - interps (iterable): Itarable of interpolation objects for -log(LH)
         distributions. 

         - prefactors (iterable): scaling factors of hte distributions. Each 
         distribution is (arbitrarly) scaled so that the max value is 1, hence
         min(-log(LH(x))) = 0. The prefactors will be summed, the new prefactor 
         will be added and the result will be returned as the prefactor for the 
         resulting distribution

         - grid_size (int, default 100): The number of nodes in the interpolation 
         object X-scale. 

        Returns:
         - interp: Resulting interpolation object for the -log(LH) distribution  

         - pre(double): distribution pre-factor
        """
        
        ml_t_prefactor = np.sum(prefactors)

        min_grid_size = np.min([len(k.x) for k in interps])
        # correction for delta-functions distribution of terminal nodes
        if min_grid_size < 10: # just combine the two grids
            grid = np.concatenate([k.x for k in interps])
            grid = np.unique(grid) # exclude repetitive points (terminals)
        else: # create new grid from combination of two

            opts = [self._min_interp(k) for k in interps]
            opts = [k for k in opts if k is not None]
            scale = 2 * np.max(
                [abs((np.max(opts) - np.min(opts))), 
                0.01]
                ) / self.max_node_abs_t
            grid = self._make_node_grid(np.mean(opts), grid_size, scale)
        
        node_prob = np.sum([k(grid) for k in interps], axis=0)
        
        pre =  node_prob.min() 
        node_prob -= pre
        
        ml_t_prefactor += pre
        
        node_prob[((0,-1),)] = -1 * self.MIN_LOG # +1000
        node_prob[((1,-2),)] = -1 * self.MIN_LOG / 2 # +500           

        interp = interp1d(grid, node_prob, kind='linear')
        return interp, ml_t_prefactor
    
    def _ml_t_leaves_root(self, grid_size=100):
        """
        Propagate up- messages for ML computations with temporal constraints.
        To each node, sets the grid and the likelihood distribution on the grid
        """

        for node in self.tree.find_clades(order='postorder'):  # down->up
            
            if node.is_terminal():
                continue # either have constraints, or will be optimized freely on the way back

            # we already have processed the node
            if hasattr(node, "neg_log_prob") and node.neg_log_prob is not None:
                continue

            # children nodes with constraints
            clades = [k for k in node.clades if k.neg_log_prob is not None]
            if len(clades) < 1:  # we need at least one constrainted
                continue
            neg_log_prob = [self._convolve(clade.neg_log_prob, 
                               clade.branch_neg_log_prob, 
                               inverse_time=True, 
                               grid_size=grid_size
                               )
                for clade in clades]
            
            new_neglogprob, prefactor = self._multiply_dists(
                neg_log_prob, 
                [k.ml_t_prefactor for k in node.clades],
                grid_size)
            node.neg_log_prob = new_neglogprob
            node.ml_t_prefactor += prefactor

            

            #import ipdb; ipdb.set_trace()
                        
            # plt.plot(node.neg_log_prob.x,node.neg_log_prob(node.neg_log_prob.x), 'o-' ); plt.xlim(0.2, 0.22)
            # log0 = neg_log_prob [0]
            # log1 = neg_log_prob [1]
            # x0 = log0.x
            # x1 = log1.x
            # plt.plot(x0, log0(x0) - log0(x0).min(), 'o--')
            # plt.plot(x1, log1(x1) - log1(x1).min(), 'o--')

    def _ml_t_root_leaves(self, grid_size=100):
        """
        Propagate down- messages for ML computations with temporal constraints.
        for each node, set the grid and the likelihood distribution of the
        position on the on the grid
        """
        for node in self.tree.find_clades(order='preorder'):  # up->down
            if not hasattr(node, "neg_log_prob"):
                print ("ERROR: node has no log-prob interpolation object! "
                    "Aborting.")
            if node.up is None:  # root node
                self._set_final_date(node) 
                
                continue               
            
            if node.neg_log_prob is not None: # aconstrained terminal 
                                              # and all internal nodes
                #if node.is_terminal():
                #    import ipdb; ipdb.set_trace()

                msg_from_root = self._convolve(node.up.neg_log_prob, 
                                                  node.branch_neg_log_prob,
                                                  inverse_time=False, 
                                                  grid_size=grid_size
                                                  )
                final_prob, final_pre = self._multiply_dists(
                            (
                                msg_from_root, 
                                node.neg_log_prob
                            ), 
                            (
                                node.ml_t_prefactor,
                                node.up.ml_t_prefactor
                            ), 
                            grid_size
                        )
                
                if self._min_interp(final_prob) < self._min_interp(node.up.neg_log_prob):
                    import ipdb; ipdb.set_trace()
                node.neg_log_prob = final_prob
                node.ml_t_prefactor = final_pre
                
            else: # unconstrained terminal nodes
                msg_from_root = self._convolve(node.up.neg_log_prob, 
                                                  node.branch_neg_log_prob,
                                                  inverse_time=False, 
                                                  grid_size=grid_size
                                                  )
               
                node.neg_log_prob = msg_from_root
                node.ml_t_prefactor = node.up.ml_t_prefactor
            
            
            #node.abs_t = self._min_interp(node.neg_log_prob)
            #node.branch_length = node.abs_t - node.up.abs_t
            #if node.branch_length < 0:
            #    import ipdb; ipdb.set_trace()

            self._set_final_date(node)            
            
    def _ml_t_root_leaves_tmp(self):
        for node in self.tree.find_clades(order='preorder'):  # up->down
            if not hasattr(node, "neg_log_prob"):
                print ("ERROR: node has no log-prob interpolation object! "
                    "Aborting.")
            self._set_final_date(node)
            
    def _set_final_date(self, node):
        """
        Set the final date and branch length parameters to a node. 
        """
        node.abs_t = self._min_interp(node.neg_log_prob)
        if node.up is not None:
            node.branch_length = node.abs_t - node.up.abs_t
            node.dist2root = node.up.dist2root + node.branch_length
        else:
            node.branch_length = 1.0
            node.dist2root = 0.0

        node.date = (
                    node.abs_t - self.date2dist.intersect) / self.date2dist.slope

    def _ml_t_grid_prob(self, p_parent, p_child, grid, gtr):
        """
        Compute probability for 2D grid of times

        Args:

         - p_parent(numpy.array): parent profile (left profile). Shape: axL (a
            - alphabet size, L - sequence length)

         - p_child(numpy.array): child profile (right profile). Shape: axL (a
            - alphabet size, L - sequence length)

         - grid(numpy.array): prepared grid of times (branch lengths) to
         compute the probabilites for double-gridded nodes. The grid must have
         shape of (Lc, Lp, L), where Lc is the length of child grid, Lp is the
         length of the parent grid and L is the length of the sequence.

         - gtr(GTR): model of evolution.

         - res(numpy.array, default None): array to store results of the
         probability computations in order to avoid the construction of big
         arrays. Must have the same dimensions as grid. If set to none, the
         array will be constructed.

         - out_prob(numpy.array, default None): output probability. If
         specified, should have the shape of (Lc, Lp). If None or shape
         mismatch, will be constructed.
        """
        out_prob = np.zeros(grid.shape[:2])
        seq_l = p_parent.shape[0]

        if grid.ndim == 2:
            # grid.shape = (len(child),len(parent), 1)
            grid = grid.reshape(grid.shape + (1,))

        # indexes to exclude overlapping grids:
        idx = (
            grid >= 0).reshape(
            grid.shape[:2])  # idx.shape=(len(child),len(parent))

        # temp result
        # shape=(child_grid,parent_grid,L)
        tmp_res = np.zeros(idx.shape + (seq_l,))

        for state in range(gtr.alphabet.shape[0]):
            egrid = np.tile(np.exp(gtr.eigenmat[state] * grid), (1, 1, seq_l))
            # ma_egrid = np.ma.masked_array(egrid, idx, fill_value=0.0)
            tmp_res += (p_parent[:, state] * p_child[:, state]) * egrid

        out_prob[idx] = tmp_res.prod(-1)[idx]  # multiply along sequence
        # out_prob[~idx] = 0.0

        return out_prob

    def ml_t(self, gtr):
        """
        Perform tree optimization with temporal constarints.
        """
        #  propagate messages up
        self._ml_t_leaves_root()

        #  propagate messages down - reconstruct node positions
        # self._ml_t_root_leaves_tmp()
        self._ml_t_root_leaves()

    def date2dist_plot(self):
        """
        Plot the dependence between the node depth in the tree and the given
        node date information.
        """
        dates = []
        for node in self.tree.find_clades():
            if node.date is not None:
                dates.append((node.date, node.dist2root))
        dates = np.array(dates)

        if self.date2dist is None:
            self.date2dist = DateConversion()
            self.date2dist.intersect,\
                self.date2dist.slope,\
                self.date2dist.r_val,\
                self.date2dist.pi_val,\
                self.date2dist.sigma = stats.linregress(dates[:, 0],
                        dates[:, 1])

        plt.plot(dates[:, 0], dates[:, 1], 'o', c='r',
                 fillstyle='none', markersize=9, label='Data')

        plt.plot([0, dates[:, 0].max()],
                 [self.date2dist.intersect, self.date2dist.intersect +
                  self.date2dist.slope * dates[:, 0].max()],
                 lw=2, c='r', label='Linear regression')

        plt.grid()
        plt.ylabel("Distance from root (node depth)")
        plt.xlabel("Node date (days before present)")
        plt.title(
            "Dependence between the node depth\nand the given date time"
            " constraints of the node.\n Tree file: %s" %
            self.tree_file)
        plt.legend()

    def _set_rotated_profiles(self, node, gtr):
        """
        Set sequence and its profiles in the eigenspace of the transition
        matrix.
        """
        node.prf_r = node.profile.dot(gtr.v)
        node.prf_l = (gtr.v_inv.dot(node.profile.T)).T

    def _score_branches(self, set_color=True):
        """
        Set score to the branch. The score is how far is the branch length from 
        its optimal value
        """
        import matplotlib as mpl
        cmap = mpl.cm.get_cmap ()
        def dev(n):
            if not hasattr(n, 'branch_neg_log_prob') or\
               n.branch_neg_log_prob is None: # root node or missing
                return 0.0
            
            return abs(sciopt.minimize_scalar(n.branch_neg_log_prob).x - 
                       n.branch_length)

        # define maximal deviation from the optimal branch_length 
        max_dev = np.max([dev(n) for n in self.tree.find_clades()])
        
        if max_dev == 0.0: # branch length optimization failed everywhere
            return 

        # set score to each node and assign color according to the score
        for n in self.tree.find_clades():
            if n.branch_length is None or n.branch_length < 0:
                n.score = 1.0
            else:
                n.score = dev(n) / max_dev
            color = tuple(map(int, np.array(cmap(n.score)[:-1]) * 255))
            n.color = color
            #node.color = map(int, np.array(cmap((transform(node.__getattribute__(attribute))-vmin)/(vmax-vmin))[:-1])*255)

    def _nni(self, node):
        """
        Perform nearest-neighbour-interchange procedure, 
        choose the best local configuration
        """
        if node.up is None: # root node
            return 
        
        children = node.clades
        sisters = [k for k in node.up.clades]
        for child_pos, child in enumerate(children):
            for sister_pos, sister in enumerate(sisters):
                # exclude node from iteration:
                if sister == node:
                    continue
                # exchange 
                node.up.clades[sister_pos] = child
                node.clades[child_pos] = sister
                # compute new likelihood for the branch