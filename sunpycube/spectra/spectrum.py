# -*- coding: utf-8 -*-
# Author: Florian Mayer <florian.mayer@bitsrc.org>,
#         Mateo Inchaurrandieta <mateo.inchaurrandieta@gmail.com>
# pylint: disable=E1101, W0141
"""
Module containing the definition of the Spectrum object. Refer to the Spectrum
documentation for more details.
"""
from __future__ import absolute_import

import astropy.nddata as ndd
from astropy.modeling import models, fitting
import astropy.units as u
import numpy as np

from matplotlib import pyplot as plt

__all__ = ['Spectrum']


class Spectrum(ndd.NDDataArray):
    """
    Class representing a spectrum.

    Attributes
    ----------
    axis: np.ndarray
        One-dimensional array with the frequency or wavelength values at every
        data point.

    axis_unit: astropy unit
        The unit of the spectral axis. This must be in units of frequency or
        distance.

    errors: np.ndarray
        Standard-deviation errors for the data

    data: np.ndarray
        one-dimensional array which the intensity at a particular frequency at
        every data-point.
    """

    def __init__(self, data, axis, axis_unit, **kwargs):
        ndd.NDDataArray.__init__(self, data=data, **kwargs)
        self.axis = axis
        self.axis_unit = axis_unit

    def plot(self, axes=None, **matplot_args):
        """
        Plot spectrum onto current axes. Behaves like matplotlib.pylot.plot()

        Parameters
        ----------
        axes: matplotlib.axes object or None
            If provided the spectrum will be plotted on the given axes.
            Else the current matplotlib axes will be used.
        """

        # Get current axes
        if not axes:
            axes = plt.gca()

        params = {}
        params.update(matplot_args)

        # This is taken from mpl.pyplot.plot() as we are trying to
        # replicate that functionality

        # allow callers to override the hold state by passing hold=True|False
        washold = axes.ishold()
        hold = matplot_args.pop('hold', None)

        if hold is not None:
            axes.hold(hold)
        try:
            lines = axes.plot(self.axis, self, **params)
        finally:
            axes.hold(washold)

        return lines

    def peek(self, **matplot_args):
        """
        Plot spectrum onto a new figure.
        """
        figure = plt.figure()
        self.plot(**matplot_args)
        figure.show()

    def shift_axis(self, offset):
        """
        Shifts the entire wavelength axis by a given linear offset

        Parameters
        ----------
        offset: float or astropy Quantity
            The amount to offset by. If no unit is given the current axis unit
            is used
        """
        if not isinstance(offset, u.Quantity):
            offset *= self.axis_unit
        self.axis += offset.to(self.axis_unit)

    def map_to_axis(self, fun):
        """
        Maps a function to the given axis. This can be used for non-linear
        corrections of the axis.

        Parameters
        ----------
        fun: Function from Quantity to Quantity
            The function to apply to the wavelengths.
        """
        qtys = [tick * self.axis_unit for tick in self.axis]
        newqtys = [fun(x) for x in qtys]
        newaxis = [tick.value for tick in newqtys]
        self.axis = newaxis

    def gaussian_fit(self, line_guess=None, *extra_lines, **kwargs):
        """
        Fits a gaussian distribution to the data, and returns a fit whose
        parameters - amplitude, mean and standard deviation, among others,
        can be called.

        Parameters
        ----------
        line_guess: tuple of three floats
            The best guess for the first component of the gaussian fit. The
            syntax is (amp_guess, mean_guess, stddev_guess).
        *extra_lines: additional tuples of three ints
            Additional lines can be fitted by adding more tuples
        **kwargs: dict
            Additional keyword arguments are passed on to the fitter
        """
        if line_guess is None:
            line_guess = self._make_line_guess()
        g_init = models.Gaussian1D(amplitude=line_guess[0], mean=line_guess[1],
                                   stddev=line_guess[2])
        for (amp, mean, stddev) in extra_lines:
            g_mod = models.Gaussian1D(amplitude=amp, mean=mean, stddev=stddev)
            g_init = g_init + g_mod
        fitter = fitting.LevMarLSQFitter()
        x_range = kwargs.pop('x_range', None)
        if x_range is not None:
            arrmin = self._qty_to_pixel(x_range[0])
            arrmax = self._qty_to_pixel(x_range[1])
            fit_axis = self.axis[arrmin:arrmax]
            fit_data = self.data[arrmin:arrmax]
        else:
            fit_axis = self.axis
            fit_data = self.data
        if self.uncertainty is not None:
            errors = self.uncertainty.array
            weights = 1 / errors
            weights[self.mask] = 0
            kwargs.update({'weights': weights})
        kwargs.pop('recalc', 0)
        return fitter(g_init, fit_axis, fit_data, **kwargs)

    def _make_line_guess(self):
        """
        Makes a guess for a first approximation of the gaussian parameters.
        This only works for clear, single line profiles; it may produce
        nonsensical results in other cases.
        """
        amp = self.data.max()
        argamp = self.data.argmax()
        mean = self.axis[argamp]
        diffs = np.abs(self.data - amp / 2)
        rval = (diffs[argamp:].argmin() if diffs[argamp:].size > 0
                else len(diffs) - 1)
        lval = diffs[argamp:].argmin() if diffs[:argamp].size > 0 else 0
        stddev = (self.axis[rval] - self.axis[lval])
        return (amp, mean, stddev)

    def _qty_to_pixel(self, quantity):
        """
        Converts a quantity into a pixel position on the axis. The closest
        value will be returned.

        Parameters
        ----------
        quantity: astropy.units.Quantity
            The quantity to convert
        """
        if isinstance(quantity, u.Quantity):
            value = quantity.to(self.axis_unit).value
        else:
            value = quantity
        closest_index = (np.abs(self.axis - value)).argmin()
        return self.axis[closest_index]

    def __getitem__(self, item):
        if isinstance(item, int):
            return self.data[item]
        elif isinstance(item, float):
            return self.data[self._qty_to_pixel(item * self.axis_unit)]
        elif isinstance(item, u.Quantity):
            return self.data[self._qty_to_pixel(item)]
        elif isinstance(item, slice):
            intslice = self._intify_slice(item)
            newdata = self.data.__getitem__(intslice)
            newaxis = self.axis.__getitem__(intslice)
            return Spectrum(newdata, newaxis, self.axis_unit)
        elif isinstance(item, tuple):
            raise IndexError("Too many indices for a Spectrum")
        else:
            raise IndexError("None indices not supported")

    def _intify_slice(self, item):
        """
        Converts a slice that includes quantities to one that includes only
        ints.

        Parameters
        ----------
        item: slice
            The slice object to convert
        """
        start = item.start
        stop = item.stop
        unit = None
        if not isinstance(item.step, int):
            raise IndexError("The step must be an int")
        if isinstance(start, u.Quantity):
            unit = start.unit
            if isinstance(stop, (int, float)):
                stop *= unit
        elif isinstance(start, float):
            if isinstance(stop, u.Quantity):
                unit = stop.unit
            else:
                unit = self.axis_unit
                stop = stop * unit if stop is not None else None
            start *= unit
        elif isinstance(start, int):
            if isinstance(stop, u.Quantity):
                unit = stop.unit
                start *= unit
            elif isinstance(stop, float):
                unit = self.axis_unit
                start *= unit
                stop *= unit
        else:
            if isinstance(stop, u.Quantity):
                unit = stop.unit
            elif isinstance(stop, float):
                unit = self.axis_unit
                stop *= unit
        if unit is not None:
            start = self._qty_to_pixel(start)
            stop = self._qty_to_pixel(stop)
        return slice(start, stop, item.step)
