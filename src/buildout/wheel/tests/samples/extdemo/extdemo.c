#include <Python.h>
#include "extdemo.h"

static PyMethodDef methods[] = {{NULL}};

#if PY_MAJOR_VERSION >= 3

#define MOD_DEF(ob, name, doc, methods) \
	  static struct PyModuleDef moduledef = { \
	    PyModuleDef_HEAD_INIT, name, doc, -1, methods, }; \
	  ob = PyModule_Create(&moduledef);

#define MOD_INIT(name) PyMODINIT_FUNC PyInit_##name(void)

MOD_INIT(extdemo)
{
    PyObject *m;

    MOD_DEF(m, "extdemo", "", methods);

    PyModule_AddObject(m, "val", PyLong_FromLong(EXTDEMO));

    return m;
}

#else

PyMODINIT_FUNC
initextdemo(void)
{
    PyObject *m;
    m = Py_InitModule3("extdemo", methods, "");
#ifdef TWO
    PyModule_AddObject(m, "val", PyInt_FromLong(2));
#else
    PyModule_AddObject(m, "val", PyInt_FromLong(EXTDEMO));
#endif
}

#endif
