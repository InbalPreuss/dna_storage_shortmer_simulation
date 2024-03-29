# encoding: UTF-8
# Copyright (c) 2010 Andrew Brown <brownan@cs.duke.edu, brownan@gmail.com>
# See LICENSE.txt for license terms

from dna_storage.reedsolomon.polynomial import Polynomial

"""This module implements Reed-Solomon Encoding.
It supports arbitrary configurations for n and k, the codeword length and
message length. This can be used to adjust the error correcting power of the
code.

Warning: Because of the way I've implemented things, leading null bytes in a
message are dropped. Be careful if encoding binary data, pad the data yourself
to k bytes per block to avoid problems. Also see the nostrip option to
decode().

When called as a script, this file encodes data from standard in and outputs it
to standard out, using the standard RS code 255,223. This is suitable for
encoding text and trying it out, but don't try to encode binary data with it!

When encoding, it outputs blocks of 255 bytes, 223 of them are data (padded
with leading null bytes if necessary) and then 32 bytes of parity data.

Use the -d flag to decode data on standard in to standard out. This reads in
blocks of 255 bytes, and outputs the decoded data from them. If there are less
than 16 errors per block, your data will be recovered.
"""



class RSCoder(object):
    def __init__(self, GFint, n, k):
        """Creates a new Reed-Solomon Encoder/Decoder object configured with
        the given n and k values.
        n is the length of a codeword, must be less than p^n
        k is the length of the message, must be less than n

        The code will have error correcting power s where 2s = n - k

        """
        self.GFint = GFint
        self.alpha = GFint.alpha
        if n < 0 or k < 0:
            raise ValueError("n and k must be positive")
        if not n < (self.GFint.p ** self.GFint.n):
            raise ValueError("n must be at most {}".format(self.GFint.p ** self.GFint.n-1))
        if not k < n:
            raise ValueError("Codeword length n must be greater than message"
                    " length k")
        self.n = n
        self.k = k

        # Generate the generator polynomial for RS codes
        # g(x) = (x-α^1)(x-α^2)...(x-α^(n-k))
        g = Polynomial((self.GFint(1),))
        for i in range(1,n-k+1):
            p = Polynomial((self.GFint(1), -self.GFint(self.alpha)**i))
            g = g * p
        self.g = g

        # h(x) = (x-α^(n-k+1))...(x-α^n)
        h = Polynomial((self.GFint(1),))
        for i in range(n-k+1,n+1):
            p = Polynomial((self.GFint(1), -self.GFint(self.alpha)**i))
            h = h * p
        self.h = h

    def encode(self, message, poly=False):
        """Encode a given list of integers with reed-solomon encoding. Returns a list of
        ints with the k message ints and n-k parity ints at the end.
        
        If a message is < k bytes long, it is assumed to be padded at the front
        with zeros.

        The sequence returned is always n elements long.

        If poly is not False, returns the encoded Polynomial object instead of
        the polynomial translated back to a ints (useful for debugging)
        """
        n = self.n
        k = self.k

        if len(message)>k:
            raise ValueError("Message length is max %d. Message was %d" % (k,
                len(message)))

        # Encode message as a polynomial:
        m = Polynomial(self.GFint(x) for x in message)

        # Shift polynomial up by n-k by multiplying by x^(n-k)
        mprime = m * Polynomial((self.GFint(1),) + (self.GFint(0),)*(n-k))

        # mprime = q*g + b for some q
        # so let's find b:
        b = mprime % self.g

        # Subtract out b, so now c = q*g
        c = mprime - b
        # Since c is a multiple of g, it has (at least) n-k roots: α^1 through
        # α^(n-k)

        if poly:
            return c

        # Turn the polynomial c back into a list of ints
        return [0]*(n-len(c.coefficients)) + list(c.coefficients)
        # return "".join(chr(x) for x in c.coefficients).rjust(n, "\0")

    def verify(self, code):
        """Verifies the code is valid by testing that the code as a polynomial
        code divides g
        returns True/False
        """
        n = self.n
        k = self.k
        h = self.h
        g = self.g

        c = Polynomial(self.GFint(x) for x in code)

        # This works too, but takes longer. Both checks are just as valid.
        #return (c*h)%gtimesh == Polynomial(x0=0)

        # Since all codewords are multiples of g, checking that code divides g
        # suffices for validating a codeword.
        return c % g == Polynomial(x0=0)

    def decode(self, r):
        """Given a received list of ints r, attempts to decode it. If
        it's a valid codeword, or if there are no more than (n-k)/2 errors, the
        message is returned.

        A message always has k ints, if a message contained less it is left padded with zeros.
        The messages returned are always k ints long.
        """
        n = self.n
        k = self.k

        if self.verify(r):
            # The last n-k bytes are parity
            ret = r[:-(n-k)]
            return [0]*(k-len(ret)) + ret

        # Turn r into a polynomial
        r = Polynomial(self.GFint(x) for x in r)
        # print r

        # Compute the syndromes:
        sz = self._syndromes(r)
        # print sz

        # Find the error locator polynomial and error evaluator polynomial
        # using the Berlekamp-Massey algorithm
        sigma, omega = self._berlekamp_massey(sz)

        # Now use Chien's procedure to find the error locations
        # j is an array of integers representing the positions of the errors, 0
        # being the rightmost position
        # X is a corresponding array of GF(5) values where X_i = self.alpha^(j_i)
        X, j = self._chien_search(sigma)
        # print X,j

        # And finally, find the error magnitudes with Forney's Formula
        # Y is an array of GF(5) values corresponding to the error magnitude
        # at the position given by the j array
        Y = self._forney(omega, X)
        # print Y

        # Put the error and locations together to form the error polynomial
        Elist = []
        for i in range(self.GFint.p**self.GFint.n -1):
            if i in j:
                Elist.append(Y[j.index(i)])
            else:
                Elist.append(self.GFint(0))
        E = Polynomial(reversed(Elist))
        # print E

        # And we get our real codeword!
        c = r - E
        # print c

        # Form it back into a string and return all but the last n-k bytes
        ret = list(c.coefficients[:-(n - k)])
        # ret = "".join(chr(x) for x in c.coefficients[:-(n-k)])
        #                                            :-(

        # Polynomial objects don't store leading 0 coefficients, so we
        # actually need to pad this to k bytes
        return [0]*(k-len(ret)) + ret


    def _syndromes(self, r):
        """Given the received codeword r in the form of a Polynomial object,
        computes the syndromes and returns the syndrome polynomial
        """
        n = self.n
        k = self.k

        # s[l] is the received codeword evaluated at α^l for 1 <= l <= s
        s = [self.GFint(0)] # s[0] is 0 (coefficient of z^0)
        for l in range(1, n-k+1):
            s.append( r.evaluate( self.GFint(self.alpha)**l ) )

        # Now build a polynomial out of all our s[l] values
        # s(z) = sum(s_i * z^i, i=1..inf)
        sz = Polynomial( reversed( s ) )

        return sz

    def _berlekamp_massey(self, s):
        """Computes and returns the error locator polynomial (sigma) and the
        error evaluator polynomial (omega)
        The parameter s is the syndrome polynomial (syndromes encoded in a
        generator function) as returned by _syndromes. Don't be confused with
        the other s = (n-k)/2

        Notes:
        The error polynomial:
        E(x) = E_0 + E_1 x + ... + E_(n-1) x^(n-1)

        j_1, j_2, ..., j_s are the error positions. (There are at most s
        errors)

        Error location X_i is defined: X_i = α^(j_i)
        that is, the power of α corresponding to the error location

        Error magnitude Y_i is defined: E_(j_i)
        that is, the coefficient in the error polynomial at position j_i

        Error locator polynomial:
        sigma(z) = Product( 1 - X_i * z, i=1..s )
        roots are the reciprocals of the error locations
        ( 1/X_1, 1/X_2, ...)

        Error evaluator polynomial omega(z) not written here
        """
        n = self.n
        k = self.k

        # Initialize:
        sigma =  [ Polynomial((self.GFint(1),)) ]
        omega =  [ Polynomial((self.GFint(1),)) ]
        tao =    [ Polynomial((self.GFint(1),)) ]
        gamma =  [ Polynomial((self.GFint(0),)) ]
        D =      [ 0 ]
        B =      [ 0 ]

        # Polynomial constants:
        ONE = Polynomial(z0=self.GFint(1))
        ZERO = Polynomial(z0=self.GFint(0))
        Z = Polynomial(z1=self.GFint(1))
        
        # Iteratively compute the polynomials 2s times. The last ones will be
        # correct
        for l in range(0, n-k):
            # Goal for each iteration: Compute sigma[l+1] and omega[l+1] such that
            # (1 + s)*sigma[l] == omega[l] in mod z^(l+1)

            # For this particular loop iteration, we have sigma[l] and omega[l],
            # and are computing sigma[l+1] and omega[l+1]
            
            # First find Delta, the non-zero coefficient of z^(l+1) in
            # (1 + s) * sigma[l]
            # This delta is valid for l (this iteration) only
            Delta = ( (ONE + s) * sigma[l] ).get_coefficient(l+1)
            # Make it a polynomial of degree 0
            Delta = Polynomial(x0=Delta)

            # Can now compute sigma[l+1] and omega[l+1] from
            # sigma[l], omega[l], tao[l], gamma[l], and Delta
            sigma.append( sigma[l] - Delta * Z * tao[l] )
            omega.append( omega[l] - Delta * Z * gamma[l] )

            # Now compute the next tao and gamma
            # There are two ways to do this
            if Delta == ZERO or 2*D[l] > (l+1):
                # Rule A
                D.append( D[l] )
                B.append( B[l] )
                tao.append( Z * tao[l] )
                gamma.append( Z * gamma[l] )

            elif Delta != ZERO and 2*D[l] < (l+1):
                # Rule B
                D.append( l + 1 - D[l] )
                B.append( 1 - B[l] )
                tao.append( sigma[l] // Delta )
                gamma.append( omega[l] // Delta )
            elif 2*D[l] == (l+1):
                if B[l] == 0:
                    # Rule A (same as above)
                    D.append( D[l] )
                    B.append( B[l] )
                    tao.append( Z * tao[l] )
                    gamma.append( Z * gamma[l] )

                else:
                    # Rule B (same as above)
                    D.append( l + 1 - D[l] )
                    B.append( 1 - B[l] )
                    tao.append( sigma[l] // Delta )
                    gamma.append( omega[l] // Delta )
            else:
                raise Exception("Code shouldn't have gotten here")


        return sigma[-1], omega[-1]

    def _chien_search(self, sigma):
        """Recall the definition of sigma, it has s roots. To find them, this
        function evaluates sigma at all non-zero points to find the roots
        The inverse of the roots are X_i, the error locations

        Returns a list X of error locations, and a corresponding list j of
        error positions (the discrete log of the corresponding X value) The
        lists are up to s elements large.

        Important technical math note: This implementation is not actually
        Chien's search. Chien's search is a way to evaluate the polynomial
        such that each evaluation only takes constant time. This here simply
        does 255 evaluations straight up, which is much less efficient.
        """
        X = []
        j = []
        p = self.GFint(self.alpha)
        for l in range(1,self.GFint.p**self.GFint.n):
            # These evaluations could be more efficient, but oh well
            if sigma.evaluate( p**l ) == 0:
                # print l
                X.append( p**(-l) )
                # This is different than the notes, I think the notes were in error
                # Notes said j values were just l, when it's actually 4-l
                ## Leon test
                j.append(self.GFint.p**self.GFint.n - l - 1)
                #j.append(l)
                # print 'X,j', X,j
        return X, j

    def _forney(self, omega, X):
        """Computes the error magnitudes"""
        # XXX Is floor division okay here? Should this be ceiling?
        s = (self.n - self.k) // 2

        Y = []

        for l, Xl in enumerate(X):
            # Compute the first part of Yl
            Yl = Xl**s
            Yl *= omega.evaluate( Xl.inverse() )
            Yl *= Xl.inverse()

            # Compute the sequence product and multiply its inverse in
            prod = self.GFint(1)
            for ji in range(s):
                if ji == l:
                    continue
                if ji < len(X):
                    Xj = X[ji]
                else:
                    Xj = self.GFint(0)
                prod = prod * (Xl - Xj)
            Yl = Yl * prod.inverse()

            Y.append(Yl)
        return Y

if __name__ == "__main__":
    pass
    # coder = RSCoder(255,223)
    # if "-d" in sys.argv:
    #     method = coder.decode
    #     blocksize = 255
    # else:
    #     method = coder.encode
    #     blocksize = 223
    #
    # while True:
    #     block = sys.stdin.read(blocksize)
    #     if not block: break
    #     code = method(block)
    #     sys.stdout.write(code)


